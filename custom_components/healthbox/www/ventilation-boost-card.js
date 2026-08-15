// ventilation-boost-card.js
// Renson Healthbox room boost control card for Home Assistant Lovelace
//
// Bundled with the integration - registered automatically as a Lovelace
// resource on startup (see async_setup_entry in __init__.py). No manual
// "Resources" setup needed; just add a dashboard card with:
//
//   type: custom:ventilation-boost-card
//   entity: fan.keuken_living_boost              (required)
//   airflow_sensor: sensor.living_airflow_ventilation_rate
//   aq_sensor: sensor.living_co2_concentration   (or VOC sensor; omit for humidity-only rooms)
//   humidity_sensor: sensor.living_humidity
//   name: Living                                 (optional override)
//   default_preset: "30 min"                     (optional)
//   default_level: 75                            (optional, 10–100)
//   default_level_entity: number.living_default_boost_level      (optional)
//   default_duration_entity: select.living_default_boost_duration (optional)
//
// Boost level is expressed in the SAME units Home Assistant reports back
// (fan.percentage, 10–100). 100% is the entity's maximum — the Renson
// integration maps that onto the Healthbox's own 0–200 boost scale — so what
// you set is exactly what the card reads back, with full power still available.
// Legacy configs using the old 10–200 scale (e.g. default_level: 150) are
// converted automatically.
//
// default_level_entity / default_duration_entity point at the integration's
// own per-room "Default Boost Level" / "Default Boost Duration" config
// entities. When set, the card's stepper/chips mirror those entities live
// (while the boost is off) instead of a fixed default_level/default_preset —
// so changing the preference anywhere in HA updates what this card starts
// with. The card stops mirroring the moment you touch the stepper/chips
// yourself, until the dashboard is reloaded.

const CARD_VERSION = '3.1.0'; // keep in sync with CARD_VERSION in __init__.py

const LEVEL_MIN  = 10;
const LEVEL_MAX  = 100;
const LEVEL_STEP = 5;

const PRESETS = [
  { label: '5 min',   short: '5′',  sec: 300   },
  { label: '15 min',  short: '15′', sec: 900   },
  { label: '30 min',  short: '30′', sec: 1800  },
  { label: '1 hour',  short: '1h',  sec: 3600  },
  { label: '2 hours', short: '2h',  sec: 7200  },
  { label: '4 hours', short: '4h',  sec: 14400 },
];

const PRESET_SECS  = Object.fromEntries(PRESETS.map(p => [p.label, p.sec]));
const PRESET_SHORT = Object.fromEntries(PRESETS.map(p => [p.label, p.short]));

const SEV_COLOR = { green: '#16A34A', amber: '#D97706', red: '#DC2626' };

function fmtTime(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  if (m > 0) return sec > 0 ? `${m}m ${String(sec).padStart(2, '0')}s` : `${m}m`;
  return `${sec}s`;
}

function co2Sev(v) {
  if (v < 1100) return { color: 'green', label: 'Good' };
  if (v < 1600) return { color: 'amber', label: 'Elevated' };
  return { color: 'red', label: 'High' };
}

function vocSev(v) {
  if (v < 700)  return { color: 'green', label: 'Good' };
  if (v < 1500) return { color: 'amber', label: 'Elevated' };
  return { color: 'red', label: 'High' };
}

function humSev(v) {
  if (v >= 40 && v < 60) return { color: 'green', label: 'Good' };
  if (v >= 60 && v < 70) return { color: 'amber', label: 'High' };
  if (v >= 20 && v < 40) return { color: 'amber', label: 'Low' };
  if (v >= 70)           return { color: 'red',   label: 'Very high' };
  return { color: 'red', label: 'Very low' };
}

// ─────────────────────────────────────────────────────────────────────────────

class VentilationBoostCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config        = null;
    this._hass          = null;
    this._boostLevel    = 75;
    this._selectedPreset = '30 min';
    this._tickInterval  = null;
    this._built         = false;
    this._levelTouched  = false;
    this._presetTouched = false;
  }

  // ── Lovelace API ──────────────────────────────────────────────────────────

  setConfig(config) {
    if (!config.entity) throw new Error('ventilation-boost-card: entity is required');
    this._config = config;
    if (config.default_preset && PRESET_SECS[config.default_preset])
      this._selectedPreset = config.default_preset;
    if (config.default_level) {
      // Accept both the new 10–100 scale and legacy 10–200 configs.
      let lvl = parseInt(config.default_level);
      if (lvl > LEVEL_MAX) lvl = Math.round(lvl / 2);
      this._boostLevel = Math.min(LEVEL_MAX, Math.max(LEVEL_MIN, lvl));
    }
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) { this._build(); this._built = true; }
    this._update();
    this._manageTick();
  }

  getCardSize() { return 4; }

  static getStubConfig() {
    return {
      entity: 'fan.keuken_living_boost',
      airflow_sensor: 'sensor.living_airflow_ventilation_rate',
      aq_sensor: 'sensor.living_co2_concentration',
      humidity_sensor: 'sensor.living_humidity',
    };
  }

  disconnectedCallback() {
    clearInterval(this._tickInterval);
    this._tickInterval = null;
  }

  // ── Data helpers ──────────────────────────────────────────────────────────

  _ent()    { return this._hass?.states[this._config.entity]; }
  _sens(k)  { const id = this._config[k]; return id ? this._hass?.states[id] : null; }
  _isOn()   { return this._ent()?.state === 'on'; }

  _remaining() {
    const e = this._ent();
    if (!e || e.state !== 'on') return 0;
    const dur     = PRESET_SECS[e.attributes.preset_mode] ?? 1800;
    const elapsed = (Date.now() - new Date(e.last_changed).getTime()) / 1000;
    return Math.max(0, Math.floor(dur - elapsed));
  }

  _airflow()      { const s = this._sens('airflow_sensor'); return s && s.state !== 'unavailable' ? Math.round(parseFloat(s.state)) : null; }

  // Mirror the integration's own "Default Boost Level" / "Default Boost
  // Duration" entities into the card's local state, while the boost is off
  // and the user hasn't locally overridden them this session.
  _syncDefaultsFromEntities() {
    if (this._isOn()) return;

    if (!this._levelTouched) {
      const s = this._sens('default_level_entity');
      if (s && s.state !== 'unavailable' && s.state !== 'unknown') {
        let lvl = parseFloat(s.state);
        if (!isNaN(lvl)) {
          if (lvl > LEVEL_MAX) lvl = Math.round(lvl / 2); // 10–200 device scale -> 10–100
          this._boostLevel = Math.min(LEVEL_MAX, Math.max(LEVEL_MIN, lvl));
        }
      }
    }

    if (!this._presetTouched) {
      const s = this._sens('default_duration_entity');
      if (s && s.state !== 'unavailable' && s.state !== 'unknown' && PRESET_SECS[s.state]) {
        this._selectedPreset = s.state;
      }
    }
  }
  _activeLevel()  { const e = this._ent(); return (e?.state === 'on') ? (e.attributes.percentage || this._boostLevel) : this._boostLevel; }
  _activePreset() { const e = this._ent(); return (e?.state === 'on') ? (e.attributes.preset_mode ?? this._selectedPreset) : this._selectedPreset; }
  _cardName()     { return this._config.name || this._ent()?.attributes.friendly_name?.replace(/\s*Boost$/i, '') || ''; }

  // ── Tick ──────────────────────────────────────────────────────────────────

  _manageTick() {
    if (this._isOn() && !this._tickInterval) {
      this._tickInterval = setInterval(() => this._update(), 1000);
    } else if (!this._isOn() && this._tickInterval) {
      clearInterval(this._tickInterval);
      this._tickInterval = null;
    }
  }

  // ── Service calls ─────────────────────────────────────────────────────────

  _startBoost() {
    // Send HA's own 10–100 percentage straight through — what you set here
    // is exactly what the entity reports back afterwards.
    this._hass.callService('fan', 'turn_on', {
      entity_id: this._config.entity,
      percentage: this._boostLevel,
      preset_mode: this._selectedPreset,
    });
  }

  _stopBoost() {
    this._hass.callService('fan', 'turn_off', {
      entity_id: this._config.entity,
    });
  }

  // ── Build shadow DOM (once) ───────────────────────────────────────────────

  _build() {
    // Detect AQ type from device_class so we can label the metric correctly
    const aqS   = this._sens('aq_sensor');
    const isVoc = aqS?.attributes.device_class === 'volatile_organic_compounds_parts';
    const aqLbl = isVoc ? 'VOC' : 'CO₂';

    // AQ panel: aq_metric slot + humidity slot (each optional)
    const aqHtml = this._config.aq_sensor ? `
      <div class="aq-metric" id="aqMetric">
        <span class="aq-lbl">${aqLbl}</span>
        <span class="aq-val" id="aqVal">—</span>
        <span class="aq-unit">ppm</span>
        <span class="aq-sev" id="aqSev">—</span>
      </div>` : '';

    const humHtml = this._config.humidity_sensor ? `
      <div class="aq-metric" id="humMetric">
        <span class="aq-lbl">Humidity</span>
        <span class="aq-val" id="humVal">—</span>
        <span class="aq-unit">%</span>
        <span class="aq-sev" id="humSev">—</span>
      </div>` : '';

    const chipHtml = PRESETS.map(p =>
      `<button class="chip" data-preset="${p.label}">${p.short}</button>`
    ).join('');

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --boost:     var(--primary-color, #0891B2);
          --surface:   var(--card-background-color, #fff);
          --ctrl:      var(--secondary-background-color, #f0f0f0);
          --border:    var(--divider-color, #e0e0e0);
          --text:      var(--primary-text-color, #18181B);
          --text2:     var(--secondary-text-color, #71717A);
          --text3:     var(--disabled-text-color, #A1A1AA);
          --font:      var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif);
          --r: 14px;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }

        .card {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: var(--r);
          overflow: hidden;
          font-family: var(--font);
        }

        /* Header */
        .hdr { display: flex; align-items: center; gap: 8px; padding: 14px 16px 10px; }
        .hdr-name {
          font-size: 15px; font-weight: 700; flex: 1;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
          color: var(--text);
        }
        .hdr-state {
          font-size: 12px; color: var(--text2);
          font-variant-numeric: tabular-nums; white-space: nowrap; transition: color .2s, font-weight .2s;
        }
        .card.on .hdr-state { color: var(--boost); font-weight: 700; }

        /* Fan icon */
        .fan-icon {
          width: 26px; height: 26px; flex-shrink: 0;
          border: 1px solid var(--border); border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
        }
        .fan-svg { overflow: visible; flex-shrink: 0; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (prefers-reduced-motion: reduce) {
          .card.on .fan-blades { animation: none !important; }
        }
        .card.on .fan-blades {
          animation: spin 1.8s linear infinite;
          transform-origin: 12px 12px;
        }

        /* AQ metrics */
        .aq-panel { display: flex; gap: 10px; padding: 0 16px 14px; }
        .aq-metric {
          flex: 1; padding-left: 10px; position: relative;
          display: flex; flex-direction: column; gap: 3px;
        }
        .aq-metric::before {
          content: ''; position: absolute; left: 0; top: 2px; bottom: 2px;
          width: 3px; border-radius: 2px; background: var(--mc, var(--text3));
        }
        .aq-lbl  { font-size: 10px; letter-spacing: .05em; text-transform: uppercase; color: var(--text2); }
        .aq-val  { font-size: 22px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1; color: var(--mc, var(--text)); }
        .aq-unit { font-size: 11px; color: var(--text2); }
        .aq-sev  { font-size: 10px; font-weight: 600; letter-spacing: .03em; text-transform: uppercase; color: var(--mc, var(--text3)); }

        /* Divider */
        .divider { height: 1px; background: var(--border); margin: 0 0 12px; }

        /* Stepper — styled like the HA climate tile's -/value/+ control */
        .slider-row { padding: 0 16px 10px; }
        .stepper {
          display: flex; align-items: stretch;
          border: 1px solid var(--border); border-radius: 10px;
          overflow: hidden; background: var(--surface);
        }
        .step-btn {
          flex: 0 0 44px; height: 40px; border: none; background: transparent;
          color: var(--text); font-size: 17px; font-weight: 600; font-family: var(--font);
          cursor: pointer; display: flex; align-items: center; justify-content: center;
          transition: all .15s; line-height: 1;
        }
        .step-btn:first-child { border-right: 1px solid var(--border); }
        .step-btn:last-child  { border-left:  1px solid var(--border); }
        .step-btn:hover:not(:disabled) { color: var(--boost); }
        .step-btn:disabled { opacity: .4; cursor: default; }
        .slider-val {
          flex: 1; display: flex; align-items: center; justify-content: center;
          font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums;
          color: var(--text); transition: color .2s;
        }
        .card.on .slider-val { color: var(--boost); }

        /* Chips */
        .chip-strip { display: flex; gap: 4px; padding: 0 16px 10px; }
        .chip {
          flex: 1; background: var(--ctrl); border: 1.5px solid transparent;
          border-radius: 6px; padding: 6px 2px; font-size: 11px; font-weight: 500;
          color: var(--text2); text-align: center; cursor: pointer;
          font-family: var(--font); transition: all .15s;
        }
        .chip:hover { color: var(--text); }
        .chip.sel { border-color: var(--boost); color: var(--boost); font-weight: 600; }
        .chip.on  { background: var(--boost); color: #fff; border-color: var(--boost); }

        /* Action button — same colour scheme as the preset chips */
        .action-btn {
          display: block; margin: 0 16px 16px; padding: 8px;
          background: var(--ctrl); color: var(--text2);
          border: 1.5px solid transparent; border-radius: 8px;
          font-size: 12px; font-weight: 600; white-space: nowrap;
          cursor: pointer; font-family: var(--font); transition: all .15s;
          width: calc(100% - 32px); text-align: center;
        }
        .action-btn:hover { color: var(--text); }
        .action-btn.on { background: var(--boost); color: #fff; }
      </style>

      <div class="card" id="card">
        <div class="hdr">
          <span class="fan-icon">
            <svg class="fan-svg" width="16" height="16" viewBox="0 0 24 24">
              <g class="fan-blades" id="fanBlades" fill="var(--text2)">
                <ellipse cx="12" cy="7.5" rx="2.4" ry="4.8" transform="rotate(0 12 12)"/>
                <ellipse cx="12" cy="7.5" rx="2.4" ry="4.8" transform="rotate(120 12 12)"/>
                <ellipse cx="12" cy="7.5" rx="2.4" ry="4.8" transform="rotate(240 12 12)"/>
                <circle cx="12" cy="12" r="2.2"/>
              </g>
            </svg>
          </span>
          <span class="hdr-name" id="cardName"></span>
          <span class="hdr-state" id="hdrState"></span>
        </div>

        <div class="aq-panel">${aqHtml}${humHtml}</div>

        <div class="divider"></div>

        <div class="slider-row">
          <div class="stepper">
            <button class="step-btn" id="levelDown" aria-label="Decrease boost level">−</button>
            <span class="slider-val" id="sliderVal">${this._boostLevel}%</span>
            <button class="step-btn" id="levelUp" aria-label="Increase boost level">+</button>
          </div>
        </div>

        <div class="chip-strip" id="chipStrip">${chipHtml}</div>

        <button class="action-btn" id="actionBtn"></button>
      </div>
    `;

    // Events
    const step = delta => {
      if (this._isOn()) return;
      this._levelTouched = true;
      this._boostLevel = Math.min(LEVEL_MAX, Math.max(LEVEL_MIN, this._boostLevel + delta));
      this.shadowRoot.getElementById('sliderVal').textContent = `${this._boostLevel}%`;
      this._updateStepButtons();
      this._updateButton();
    };
    this.shadowRoot.getElementById('levelDown').addEventListener('click', () => step(-LEVEL_STEP));
    this.shadowRoot.getElementById('levelUp').addEventListener('click', () => step(LEVEL_STEP));

    this.shadowRoot.getElementById('chipStrip').addEventListener('click', e => {
      if (this._isOn()) return;
      const chip = e.target.closest('[data-preset]');
      if (!chip) return;
      this._presetTouched = true;
      this._selectedPreset = chip.dataset.preset;
      this._updateChips();
      this._updateButton();
    });

    this.shadowRoot.getElementById('actionBtn').addEventListener('click', () => {
      this._isOn() ? this._stopBoost() : this._startBoost();
    });
  }

  // ── Update (called on every hass change + every 1-second tick) ───────────

  _update() {
    if (!this._built) return;

    this._syncDefaultsFromEntities();

    const on      = this._isOn();
    const rem     = this._remaining();
    const level   = this._activeLevel();
    const af      = this._airflow();
    const card    = this.shadowRoot.getElementById('card');

    card.classList.toggle('on', on);

    // Name
    this.shadowRoot.getElementById('cardName').textContent = this._cardName();

    // Fan icon colour
    this.shadowRoot.getElementById('fanBlades')
      .setAttribute('fill', on ? 'var(--boost)' : 'var(--text2)');

    // Header state: "95%" at rest  |  "150% · 1h 20m" when boosting
    const hdrEl = this.shadowRoot.getElementById('hdrState');
    hdrEl.textContent = on
      ? `${level}% · ${fmtTime(rem)}`
      : (af != null ? `${af}%` : '');

    // AQ metrics
    this._updateAqMetrics();

    // Stepper
    this.shadowRoot.getElementById('sliderVal').textContent =
      `${on ? level : this._boostLevel}%`;
    this._updateStepButtons(on);

    // Chips + button
    this._updateChips();
    this._updateButton(rem, level);
  }

  _updateAqMetrics() {
    // CO₂ / VOC
    if (this._config.aq_sensor) {
      const s = this._sens('aq_sensor');
      if (s && s.state !== 'unavailable') {
        const val   = parseFloat(s.state);
        const isVoc = s.attributes.device_class === 'volatile_organic_compounds_parts';
        const sev   = isVoc ? vocSev(val) : co2Sev(val);
        const m = this.shadowRoot.getElementById('aqMetric');
        if (m) {
          m.style.setProperty('--mc', SEV_COLOR[sev.color]);
          this.shadowRoot.getElementById('aqVal').textContent = isNaN(val) ? '—' : Math.round(val);
          this.shadowRoot.getElementById('aqSev').textContent = sev.label;
        }
      }
    }

    // Humidity
    if (this._config.humidity_sensor) {
      const s = this._sens('humidity_sensor');
      if (s && s.state !== 'unavailable') {
        const val = parseFloat(s.state);
        const sev = humSev(val);
        const m = this.shadowRoot.getElementById('humMetric');
        if (m) {
          m.style.setProperty('--mc', SEV_COLOR[sev.color]);
          this.shadowRoot.getElementById('humVal').textContent = isNaN(val) ? '—' : Math.round(val);
          this.shadowRoot.getElementById('humSev').textContent = sev.label;
        }
      }
    }
  }

  _updateStepButtons(on) {
    const down = this.shadowRoot.getElementById('levelDown');
    const up   = this.shadowRoot.getElementById('levelUp');
    if (!down || !up) return;
    on = on ?? this._isOn();
    down.disabled = on || this._boostLevel <= LEVEL_MIN;
    up.disabled   = on || this._boostLevel >= LEVEL_MAX;
  }

  _updateChips() {
    const on     = this._isOn();
    const active = this._activePreset();
    this.shadowRoot.querySelectorAll('.chip').forEach(c => {
      c.classList.toggle('sel', !on && c.dataset.preset === active);
      c.classList.toggle('on',   on && c.dataset.preset === active);
    });
  }

  _updateButton(rem, level) {
    const btn = this.shadowRoot.getElementById('actionBtn');
    if (!btn) return;
    const on = this._isOn();
    btn.classList.toggle('on', on);
    if (on) {
      btn.textContent = `Stop (${fmtTime(rem ?? this._remaining())})`;
    } else {
      const short = PRESET_SHORT[this._selectedPreset] ?? this._selectedPreset;
      btn.textContent = `Start ${short} at ${this._boostLevel}%`;
    }
  }
}

customElements.define('ventilation-boost-card', VentilationBoostCard);

console.info(
  `%c VENTILATION-BOOST-CARD %c v${CARD_VERSION} `,
  'color: white; background: #0891B2; font-weight: 700;',
  'color: #0891B2; background: white; font-weight: 700;'
);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'ventilation-boost-card',
  name: 'Ventilation Boost Card',
  description: 'Renson Healthbox room boost with live CO₂ / VOC / humidity',
  preview: true,
});
