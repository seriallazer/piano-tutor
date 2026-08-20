import { useEffect, useMemo, useRef, useState } from 'react';
import { emitVirtualMidi } from '../../src/plugin-api/index';

interface PracticePianoKeyboardProps {
  targetPitches?: readonly number[];
}

const START_NOTE = 21; // A0 — first key on an 88-key piano
const END_NOTE = 108; // C8 — last key on an 88-key piano
const BLACK_PITCH_CLASSES = new Set([1, 3, 6, 8, 10]);
const NOTE_NAMES = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];

function isBlack(note: number): boolean {
  return BLACK_PITCH_CLASSES.has(note % 12);
}

function labelFor(note: number): string {
  const octave = Math.floor(note / 12) - 1;
  return `${NOTE_NAMES[note % 12]}${octave}`;
}

export function PracticePianoKeyboard({ targetPitches = [] }: PracticePianoKeyboardProps) {
  const notes = useMemo(
    () => Array.from({ length: END_NOTE - START_NOTE + 1 }, (_, index) => START_NOTE + index),
    [],
  );
  const whiteNotes = useMemo(() => notes.filter((note) => !isBlack(note)), [notes]);
  const blackNotes = useMemo(() => notes.filter(isBlack), [notes]);
  const [activeNotes, setActiveNotes] = useState<ReadonlySet<number>>(new Set());
  const pointerNotes = useRef(new Map<number, number>());
  const scrollRef = useRef<HTMLDivElement>(null);
  const targets = useMemo(() => new Set(targetPitches), [targetPitches]);
  const focusNote = targetPitches[0] ?? 60;

  // Keep the current target centred. With no active exercise, centre middle C.
  useEffect(() => {
    const key = scrollRef.current?.querySelector<HTMLElement>(`[data-midi-note="${focusNote}"]`);
    key?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [focusNote]);

  function attack(note: number, pointerId: number, timestamp: number, element: HTMLButtonElement) {
    if (pointerNotes.current.has(pointerId)) return;
    pointerNotes.current.set(pointerId, note);
    element.setPointerCapture?.(pointerId);
    setActiveNotes((current) => new Set(current).add(note));
    emitVirtualMidi({
      midiNote: note,
      timestamp,
      velocity: 96,
      type: 'attack',
    });
  }

  function release(pointerId: number, timestamp: number) {
    const note = pointerNotes.current.get(pointerId);
    if (note === undefined) return;
    pointerNotes.current.delete(pointerId);
    setActiveNotes((current) => {
      const next = new Set(current);
      next.delete(note);
      return next;
    });
    emitVirtualMidi({
      midiNote: note,
      timestamp,
      type: 'release',
    });
  }

  function keyClass(note: number, color: 'white' | 'black'): string {
    return [
      'practice-piano__key',
      `practice-piano__key--${color}`,
      activeNotes.has(note) ? 'practice-piano__key--active' : '',
      targets.has(note) ? 'practice-piano__key--target' : '',
    ].filter(Boolean).join(' ');
  }

  return (
    <section className="practice-piano" aria-label="On-screen practice piano">
      <div className="practice-piano__intro">
        <span><strong>88-key touch piano</strong> · use this until the USB MIDI cable arrives</span>
        <span className="practice-piano__hint">Target notes glow amber</span>
      </div>
      <div className="practice-piano__scroll" ref={scrollRef}>
        <div className="practice-piano__keys">
          <div className="practice-piano__white-row">
            {whiteNotes.map((note) => (
              <button
                key={note}
                type="button"
                className={keyClass(note, 'white')}
                data-midi-note={note}
                aria-label={`Play ${labelFor(note)}`}
                onPointerDown={(event) => {
                  event.preventDefault();
                  attack(note, event.pointerId, event.timeStamp, event.currentTarget);
                }}
                onPointerUp={(event) => release(event.pointerId, event.timeStamp)}
                onPointerCancel={(event) => release(event.pointerId, event.timeStamp)}
              >
                {note % 12 === 0 && <span>{labelFor(note)}</span>}
              </button>
            ))}
          </div>
          {blackNotes.map((note) => {
            const whitesBefore = whiteNotes.filter((white) => white < note).length;
            const boundary = (whitesBefore / whiteNotes.length) * 100;
            return (
              <button
                key={note}
                type="button"
                className={keyClass(note, 'black')}
                data-midi-note={note}
                style={{ left: `calc(${boundary}% - 12px)` }}
                aria-label={`Play ${labelFor(note)}`}
                onPointerDown={(event) => {
                  event.preventDefault();
                  attack(note, event.pointerId, event.timeStamp, event.currentTarget);
                }}
                onPointerUp={(event) => release(event.pointerId, event.timeStamp)}
                onPointerCancel={(event) => release(event.pointerId, event.timeStamp)}
              />
            );
          })}
        </div>
      </div>
    </section>
  );
}
