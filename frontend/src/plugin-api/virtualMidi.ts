import type { PluginNoteEvent } from './types';

/**
 * Browser-local MIDI bus used by the touch piano and by automated demos.
 *
 * Events enter the exact same PluginContext MIDI stream as a hardware keyboard,
 * so practice scoring never needs a separate "easy mode" implementation.
 */
export const VIRTUAL_MIDI_EVENT = 'piano-tutor:virtual-midi';

export function emitVirtualMidi(event: PluginNoteEvent): void {
  window.dispatchEvent(new CustomEvent<PluginNoteEvent>(VIRTUAL_MIDI_EVENT, {
    detail: event,
  }));
}
