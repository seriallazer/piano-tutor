import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { VIRTUAL_MIDI_EVENT } from '../../src/plugin-api/index';
import type { PluginNoteEvent } from '../../src/plugin-api/index';
import { PracticePianoKeyboard } from './PracticePianoKeyboard';

describe('PracticePianoKeyboard', () => {
  it('emits attack and release events through the virtual MIDI bus', () => {
    const received: PluginNoteEvent[] = [];
    const listener = vi.fn((event: Event) => {
      received.push((event as CustomEvent<PluginNoteEvent>).detail);
    });
    window.addEventListener(VIRTUAL_MIDI_EVENT, listener);

    render(<PracticePianoKeyboard />);
    const middleC = screen.getByRole('button', { name: 'Play C4' });
    fireEvent.pointerDown(middleC, { pointerId: 7, timeStamp: 100 });
    fireEvent.pointerUp(middleC, { pointerId: 7, timeStamp: 160 });

    expect(received.map((event) => [event.type, event.midiNote])).toEqual([
      ['attack', 60],
      ['release', 60],
    ]);
    window.removeEventListener(VIRTUAL_MIDI_EVENT, listener);
  });

  it('visually marks the current target pitch', () => {
    render(<PracticePianoKeyboard targetPitches={[60, 64]} />);
    expect(screen.getByRole('button', { name: 'Play C4' })).toHaveClass('practice-piano__key--target');
    expect(screen.getByRole('button', { name: 'Play E4' })).toHaveClass('practice-piano__key--target');
    expect(screen.getByRole('button', { name: 'Play D4' })).not.toHaveClass('practice-piano__key--target');
  });
});
