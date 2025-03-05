# py_nes_emulator
NES emulator written in Python

This is just a toy example to learn about emulator development - optimization isn't really the goal, so I don't know if this Python version will ever be performant enough to actually play games in real-time (though I may eventually port this to C, C++, or Rust).

My main goal is to get this to the point where it can emulate Super Mario Bros - and with it, most mapper 0 games. Though not necessarily in real time (see next section...)

### Probably Out of scope

**Being optimized enough to actually play games in real-time.** Performance is better than I expected it would be, and I'm able to emulate games at 20-30 FPS. But still, this is Python - it's not really intended for emulating a few million CPU & PPU instructions per second, and as such its bytecode is not really optimized (`-O` helps a little bit, but not nearly enough). It would probably possible with some aggressive optimization, but at the expense of readability, maintainability, and "pythonic"-ness. I may try Cython, PyPy, or Numba and see if any of these help, but it's not worth it if they affect the code too much or don't play nice with dependencies.

**Perfect emulation.** For example, precise cycle accuracy, hardware quirks like open-bus behavior, or pixel-exact PPU emulation. I do expect to support some of the most common quirks that many games rely on, but definitely not Battletoads-level accuracy.

**Audio.** I love audio coding, but Python isn't the right language for real-time audio either (and the purist in me would hate to just your system's built-in MIDI)

### Optimizations

While optimizing this well enough for real-time is out of scope, there are still some optimizations.

The PPU does not run fully independently from the CPU. The CPU runs an instruction, then ticks the PPU by the appropriate number of cycles. So we don't have cycle-exact emulation, but it also means we only need to run the PPU once per CPU instruction. Additionally, many PPU checks only run at the end of a line rather than every pixel, saving us a lot of processing (at the expense of even more cycle-accuracy).

We render an entire frame at once (or portion of a frame, if the PPU is updated mid-frame), rather than pixel-by-pixel or row-by-row. This allows us to use vectorized Numpy operations as much as possible.

Sprite Zero Hit is pre-calculated at the end of VBLANK using Numpy. It is also updated whenever the PPU is updated mid-frame (if it hasn't hit already).

There are some elements of PPU rendering that could be further optimized - for example, we are rendering all nametable data, even outside the area being shown on-screen. This is useful for debugging, but not the best for performance. Similarly, there are other debug graphics being generated that could be made optional.

Finally, many games spend a lot of CPU time looping, either waiting for an interrupt or else polling PPUSTATUS waiting for it to change. The CPU emulation has logic to detect when this is happening, and instead of continuing to emulate the same few instructions over and over, we sleep the CPU and tell the PPU to skip directly to the next PPUSTATUS change. This gives a huge boost in performance (typically double the FPS). However, this only works on games where nothing happens in the main loop. Some games use this idle time to tick an RNG, and so this logic doesn't work for these games. It could still be possible to sleep the CPU in this case (if you don't need 100% exact RNG behavior - which this emulator isn't anywhere near accurate enough to get in the first place). However, detecting when we're in such a loop is much more complex, so this hasn't been implemented yet.

### Current status

There's basic emulation, but no APU or mapper support.

Working or mostly-working:

- **nestest.nes**: all "normal" opcode tests pass
- **Donkey Kong**
- **Ice Climber**
- **Galaga**
- **Balloon Fight**
- **Ice Hockey**: the title screen doesn't render properly, likely from imprecise timing
- **Super Mario Bros**: the status bar flickers once you scroll past the first screen, but otherwise it works properly

Major problems:

- **Excitebike**: Emulator hits an assert
- **Bomberman**: Freezes on title screen. Oddly, it used to get further than this (but got stuck after starting the game), when the VBLANK bit wasn't being cleared on PPUSTATUS read.

PPU & rendering issues:

- We don't limit to max 8 sprites per line
	- This might sound like a limit we don't want, but some games actually use this intentionally (like doors in The Legend of Zelda)
	- Sprite overflow flag is not set either, though thankfully there's only 1 commercial game listed on the nesdev wiki that depends on this, because of a hardware bug that makes the behavior unreliable in many cases
	- See https://www.nesdev.org/wiki/Sprite_overflow_games
- Sprite 0 hit is only line-accurate, not pixel-accurate
- PPUSCROLL & PPUADDR sharing internal registers is not handled correctly
- Exact behavior when updating PPU outside of VBLANK is not fully emulated

Next goals:

- Code cleanups
- Other PPU features & behaviors
- Basic APU emulation (without actually playing audio yet - just show audio channel info on-screen)

Lower priority stuff:

- Always make any pressed button last for at least 1 frame
	- Even though a real NES wouldn't behave this way, we usually run a lot slower than 60 FPS, so short button presses can be missed entirely
- Player 2 controller support
- PC gamepad support

Stretch goals:

- Support other mappers
- Emulate Mega Man 2
- Emulate The Legend of Zelda

### Other related ideas

Try to emulate as much of the PPU behavior on the GPU as possible

Try to emulate CPU & PPU in separate threads, or possibly with coroutines

Take a ROM disassembly and JIT compile it into something which can be emulated much more efficiently

Taking a ROM disassembly and converting it into C/C++ code which can then be compiled natively

- No, I don't mean converting it into code which can be compiled into the same assembly - but rather, functionally equivalent code
- I also wouldn't expect this to be nice clean readable code
- Similar to what was reportedly done for the original Mega Man Legacy Collection

Write my own disassembler
