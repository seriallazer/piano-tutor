import { useEffect, useRef, useState } from 'react';
import { SMUFL_CODEPOINTS } from '../types/notation/config';
import { useTranslation } from '../i18n/index';
import { trackEvent } from '../services/telemetry';
import './LandingScreen.css';

// ---------------------------------------------------------------------------
// Constants (Feature 001-landing-redesign)
// ---------------------------------------------------------------------------

/** Five standard duration note glyphs from the Bravura font (SMuFL spec) */
const NOTE_GLYPHS = [
  SMUFL_CODEPOINTS.WHOLE_NOTE,        // ○  \uE0A2
  SMUFL_CODEPOINTS.HALF_NOTE_UP,      // 𝅗𝅥  \uE1D3
  SMUFL_CODEPOINTS.QUARTER_NOTE_UP,   // ♩  \uE1D5
  SMUFL_CODEPOINTS.EIGHTH_NOTE_UP,    // ♪  \uE1D7
  SMUFL_CODEPOINTS.SIXTEENTH_NOTE_UP, // 𝅘𝅥𝅯  \uE1D9
  SMUFL_CODEPOINTS.TREBLE_CLEF,       // 𝄞  \uE050
  SMUFL_CODEPOINTS.BASS_CLEF,         // 𝄢  \uE062
  SMUFL_CODEPOINTS.ALTO_CLEF,         // 𝄡  \uE05C
] as const;

/**
 * Three colors from the play-view palette (LayoutRenderer.css).
 * - Slate:  #3D4B5C — softened dark, easier on the eye than pure black
 * - Amber:  #F5A340 — warm softened orange (highlighted notehead, T030/FR-012)
 * - Sage:   #5AC481 — soft jade green (pinned-position notehead, Feature 027)
 */
const NOTE_COLORS = ['#3D4B5C', '#F5A340', '#5AC481'] as const;

/** Full loop duration in seconds (Lissajous period) — 20s for a leisurely pace */
const LOOP_DURATION = 20;

/**
 * Lissajous path parameters.
 * x(t) = X_CENTER + X_AMP × sin(2πt)         → range [12%, 88%]
 * y(t) = Y_CENTER + Y_AMP × sin(4πt + Y_PHASE) → range [2%, 78%]
 *
 * Y_PHASE is computed so that y(0) ≈ 5%, placing the initial note
 * behind the app-header banner (~60px = ~8% on a 768px tablet).
 */
const X_CENTER = 50;
const X_AMP = 38;
const Y_CENTER = 40;
const Y_AMP = 38;
/** Phase offset so y(t=0) = 5% (behind the app-header) */
const Y_PHASE = Math.asin((5 - Y_CENTER) / Y_AMP); // ≈ -1.173 rad

/** Pick a random index from [0, poolSize) that is not `exclude` */
function pickRandom(poolSize: number, exclude: number): number {
  let idx = Math.floor(Math.random() * (poolSize - 1));
  if (idx >= exclude) idx += 1;
  return idx;
}

/** Evaluate the Lissajous path at normalised time t ∈ [0, 1) */
function evalPath(t: number): { x: number; y: number } {
  const angle = t * 2 * Math.PI;
  return {
    x: X_CENTER + X_AMP * Math.sin(angle),
    y: Y_CENTER + Y_AMP * Math.sin(2 * angle + Y_PHASE),
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface LandingScreenProps {
  /** Called when the user activates the Instruments action (debug mode only) */
  onShowInstruments?: () => void;
  /**
   * Core plugins to feature as launch buttons on the landing screen.
   * Only plugins with `type === 'core'` in their manifest should be included.
   */
  corePlugins?: Array<{ id: string; name: string; icon?: string }>;
  /** Called when the user taps a core plugin launch button. */
  onLaunchPlugin?: (pluginId: string) => void;
  /**
   * Feature 039: Active landing theme id (e.g. "ember").
   * When provided, applies `.theme-<id>` CSS class to the root element
   * and uses `noteColors` for the animation cycle.
   * When absent, falls back to original Feature 001 behaviour.
   */
  activeThemeId?: string;
  /**
   * Feature 039: Override the animated note colour cycle for the active theme.
   * When absent, the hardcoded NOTE_COLORS constant is used.
   */
  noteColors?: readonly [string, string, string];
}

/**
 * LandingScreen — full-viewport (100vw × 100vh) hero shown when no score is loaded.
 *
 * Features (001-landing-redesign):
 * - Covers the entire viewport behind the .app-header banner
 * - Single Bravura note glyph follows a fixed Lissajous looping path
 * - Glyph and color change simultaneously every second (no immediate repeats)
 * - Click the note to pause / resume the animation
 * - Pauses when the browser tab is hidden (Page Visibility API)
 * - Respects prefers-reduced-motion: position frozen, glyph/color still cycle
 */
export function LandingScreen({ onShowInstruments, corePlugins, onLaunchPlugin, activeThemeId, noteColors }: LandingScreenProps) {
  const { t, tDynamic } = useTranslation()
  // Read reduced-motion preference once at mount
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Position of the animated note (% of container)
  const initialPos = evalPath(0);
  const [position, setPosition] = useState(initialPos);

  // Glyph and color indices — initialised to random values
  const [glyphIdx, setGlyphIdx] = useState(() =>
    Math.floor(Math.random() * NOTE_GLYPHS.length)
  );
  // Use theme-provided colours if given, else fall back to Feature 001 defaults
  const activeColors = noteColors ?? NOTE_COLORS;

  const [colorIdx, setColorIdx] = useState(() =>
    Math.floor(Math.random() * activeColors.length)
  );
  const modeOrder: Record<string, number> = {
    'practice-view-plugin': 0,
    'train-view': 1,
    'play-score': 2,
  };
  const orderedCorePlugins = corePlugins
    ? [...corePlugins].sort((a, b) => (modeOrder[a.id] ?? 99) - (modeOrder[b.id] ?? 99))
    : [];

  // Pause/resume state — ref for rAF callbacks, state for aria/CSS
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);

  // Refs for rAF loop state (not reactive — avoid re-renders)
  const rafRef = useRef<number>(0);
  const elapsedRef = useRef<number>(0);    // total seconds of animation elapsed
  const prevTimeRef = useRef<number | null>(null); // last rAF timestamp (ms)
  const prevSecondRef = useRef<number>(-1); // last whole-second boundary ticked
  // Keep current indices accessible inside rAF callbacks without stale closures
  const glyphIdxRef = useRef(glyphIdx);
  const colorIdxRef = useRef(colorIdx);

  // Keep a ref to the active colours so rAF callbacks always read the latest value
  const activeColorsRef = useRef(activeColors);
  useEffect(() => { activeColorsRef.current = noteColors ?? NOTE_COLORS; }, [noteColors]);

  // Keep refs in sync with state
  useEffect(() => { glyphIdxRef.current = glyphIdx; }, [glyphIdx]);
  useEffect(() => { colorIdxRef.current = colorIdx; }, [colorIdx]);

  // --------------------------------------------------------------------------
  // Main rAF animation loop
  // --------------------------------------------------------------------------
  useEffect(() => {
    function tick(now: number) {
      // Pause when tab is hidden — drain stale timestamp but don't advance elapsed
      if (document.hidden) {
        prevTimeRef.current = null;
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      // Accumulate elapsed seconds
      if (prevTimeRef.current !== null) {
        elapsedRef.current += (now - prevTimeRef.current) / 1000;
      }
      prevTimeRef.current = now;

      // ------------------------------------------------------------------
      // 1-second tick: change glyph + color simultaneously (no repeats)
      // ------------------------------------------------------------------
      const currentSecond = Math.floor(elapsedRef.current);
      if (currentSecond !== prevSecondRef.current) {
        prevSecondRef.current = currentSecond;
        const nextGlyph = pickRandom(NOTE_GLYPHS.length, glyphIdxRef.current);
        const nextColor = pickRandom(activeColorsRef.current.length, colorIdxRef.current);
        setGlyphIdx(nextGlyph);
        setColorIdx(nextColor);
      }

      // ------------------------------------------------------------------
      // Position update along the Lissajous path
      // ------------------------------------------------------------------
      if (!reducedMotion) {
        const t = (elapsedRef.current % LOOP_DURATION) / LOOP_DURATION;
        setPosition(evalPath(t));
      }

      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // --------------------------------------------------------------------------
  // Tab visibility: cancel rAF when hidden, restart when visible (unless user-paused)
  // --------------------------------------------------------------------------
  useEffect(() => {
    function onVisibilityChange() {
      if (document.hidden) {
        cancelAnimationFrame(rafRef.current);
        prevTimeRef.current = null; // prevent large time-jump on resume
      } else if (!pausedRef.current) {
        rafRef.current = requestAnimationFrame(function tick(now: number) {
          if (document.hidden) {
            prevTimeRef.current = null;
            rafRef.current = requestAnimationFrame(tick);
            return;
          }
          if (prevTimeRef.current !== null) {
            elapsedRef.current += (now - prevTimeRef.current) / 1000;
          }
          prevTimeRef.current = now;

          const currentSecond = Math.floor(elapsedRef.current);
          if (currentSecond !== prevSecondRef.current) {
            prevSecondRef.current = currentSecond;
            const nextGlyph = pickRandom(NOTE_GLYPHS.length, glyphIdxRef.current);
            const nextColor = pickRandom(activeColorsRef.current.length, colorIdxRef.current);
            setGlyphIdx(nextGlyph);
            setColorIdx(nextColor);
          }

          if (!reducedMotion) {
            const t = (elapsedRef.current % LOOP_DURATION) / LOOP_DURATION;
            setPosition(evalPath(t));
          }

          rafRef.current = requestAnimationFrame(tick);
        });
      }
    }

    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // --------------------------------------------------------------------------
  // Click-to-pause / click-to-resume
  // --------------------------------------------------------------------------
  function handleNoteClick() {
    if (pausedRef.current) {
      // Resume: restart rAF, discard stale delta
      pausedRef.current = false;
      setPaused(false);
      prevTimeRef.current = null;
      rafRef.current = requestAnimationFrame(function tick(now: number) {
        if (document.hidden || pausedRef.current) {
          prevTimeRef.current = null;
          if (!pausedRef.current) rafRef.current = requestAnimationFrame(tick);
          return;
        }
        if (prevTimeRef.current !== null) {
          elapsedRef.current += (now - prevTimeRef.current) / 1000;
        }
        prevTimeRef.current = now;

        const currentSecond = Math.floor(elapsedRef.current);
        if (currentSecond !== prevSecondRef.current) {
          prevSecondRef.current = currentSecond;
          const nextGlyph = pickRandom(NOTE_GLYPHS.length, glyphIdxRef.current);
          const nextColor = pickRandom(activeColorsRef.current.length, colorIdxRef.current);
          setGlyphIdx(nextGlyph);
          setColorIdx(nextColor);
        }

        if (!reducedMotion) {
          const t = (elapsedRef.current % LOOP_DURATION) / LOOP_DURATION;
          setPosition(evalPath(t));
        }

        rafRef.current = requestAnimationFrame(tick);
      });
    } else {
      // Pause: cancel rAF and freeze elapsed time
      pausedRef.current = true;
      setPaused(true);
      cancelAnimationFrame(rafRef.current);
      prevTimeRef.current = null;
    }
  }

  // --------------------------------------------------------------------------
  // Render
  // --------------------------------------------------------------------------
  return (
    <div
      className={`landing-screen${paused ? ' landing-screen--paused' : ''}${activeThemeId ? ` theme-${activeThemeId}` : ''}`}
      data-testid="landing-screen"
      role="region"
      aria-label={paused ? t('landing.aria_paused') : t('landing.aria_playing')}
      tabIndex={-1}
      onClick={handleNoteClick}
    >
      {/* Animated Bravura note glyph */}
      <span
        className="landing-note music-glyph"
        data-testid="landing-note"
        aria-hidden="true"
        style={{
          left: `${position.x}%`,
          top: `${position.y}%`,
          color: activeColorsRef.current[colorIdx],
        }}
      >
        {NOTE_GLYPHS[glyphIdx]}
      </span>

      {/* Product dashboard — stop propagation so interaction never pauses the decoration. */}
      <div className="landing-content" onClick={e => e.stopPropagation()}>
        <div className="landing-hero" aria-labelledby="landing-headline">
          <div>
            <p className="landing-eyebrow">{t('landing.eyebrow')}</p>
            <h2 id="landing-headline" className="landing-headline">{t('landing.headline')}</h2>
            <p className="landing-body">{t('landing.body')}</p>
          </div>
          <div className="landing-session-card">
            <span className="landing-session-card__label">{t('landing.plan_title')}</span>
            <ol>
              <li><span>3 min</span>{t('landing.plan_warmup')}</li>
              <li><span>8 min</span>{t('landing.plan_focus')}</li>
              <li><span>4 min</span>{t('landing.plan_review')}</li>
            </ol>
          </div>
        </div>

        <div className="landing-mode-grid" aria-label={t('landing.modes_aria')}>
          {orderedCorePlugins.length > 0 && onLaunchPlugin && orderedCorePlugins.map((plugin) => {
            const isPractice = plugin.id === 'practice-view-plugin';
            const descriptions: Record<string, string> = {
              'practice-view-plugin': t('landing.mode.practice'),
              'train-view': t('landing.mode.train'),
              'play-score': t('landing.mode.play'),
            };
            const kickers: Record<string, string> = {
              'practice-view-plugin': t('landing.mode.practice_kicker'),
              'train-view': t('landing.mode.train_kicker'),
              'play-score': t('landing.mode.play_kicker'),
            };
            return (
              <button
                key={plugin.id}
                data-testid={`plugin-launch-${plugin.id}`}
                className={`landing-mode-card${isPractice ? ' landing-mode-card--primary' : ''}`}
                onClick={() => {
                  trackEvent('cta_click', { action: 'launch_plugin', plugin_id: plugin.id });
                  onLaunchPlugin(plugin.id);
                }}
              >
                <span className="landing-mode-card__icon" aria-hidden="true">{plugin.icon}</span>
                <span className="landing-mode-card__copy">
                  <span className="landing-mode-card__kicker">{kickers[plugin.id] ?? t('landing.mode.explore')}</span>
                  <strong>{tDynamic(`plugin.name.${plugin.id}`, plugin.name)}</strong>
                  <span>{descriptions[plugin.id] ?? plugin.name}</span>
                </span>
                <span className="landing-mode-card__arrow" aria-hidden="true">→</span>
              </button>
            );
          })}
        </div>

        <aside className="landing-device-strip" aria-label={t('landing.device_aria')}>
          <span className="landing-device-strip__status" aria-hidden="true" />
          <div>
            <strong>{t('landing.device_title')}</strong>
            <span>{t('landing.device_body')}</span>
          </div>
          <span className="landing-device-strip__badge">CDP-S300 · 88 keys</span>
        </aside>

        {onShowInstruments && (
          <button
            className="landing-instruments-btn"
            onClick={() => {
              trackEvent('cta_click', { action: 'show_instruments' });
              onShowInstruments();
            }}
          >
            {t('landing.instruments_button')}
          </button>
        )}
      </div>
    </div>
  );
}
