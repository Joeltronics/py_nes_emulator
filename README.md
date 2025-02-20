# py_nes_emulator
NES emulator written in Python

This is just a toy example to learn about emulator development - optimization isn't really the goal, so I don't know if this Python version will ever be performant enough to actually play games in real-time (though I may eventually port this to C, C++, or Rust).

My main goal is to get this to the point where it can emulate Super Mario Bros - and with it, most mapper 0 games. Though not necessarily in real time (see next section...)

### Probably Out of scope

**Being optimized enough to actually play games in real-time.** Performance is better than I expected it would be, and I'm able to emulate games at 20-30 FPS. But still, this is Python - it's not really intended for emulating a few million CPU & PPU instructions per second. It would probably possible with some aggressive optimization, but at the expense of readability, maintainability, and "pythonic"-ness.

**Perfect emulation.** For example, precise cycle accuracy, hardware quirks like open-bus behavior, or pixel-exact PPU emulation. I do expect to support some of the most common quirks that many games rely on, but definitely not Battletoads-level accuracy.

**Audio.** I love audio coding, but Python isn't the right language for real-time audio either (and the purist in me would hate to just your system's built-in MIDI)

### Current status

There's basic emulation, but no APU or mapper support:

- **Donkey Kong**: seems to work (but slow)
- **Ice Climber**: seems to work (but slow)
- **Balloon Fight**: seems to work (and not slow!), although in Balloon Trip mode the score scrolls with the level since we don't support split-screen rendering yet
- **Super Mario Bros**: Title screen doesn't work, likely due to something we're not doing right with the PPU (see below)
- **Excitebike**: Gets stuck on title screen, start & select both act as select
- **Ice Hockey**: Title screen doesn't render properly, which is expected due to some unimplemented PPU features. But what isn't expected is that it gets stuck on the title screen (problem reading controllers, similar to Excitebike?).
- **Bomberman**: Title screen works, but gets stuck on the first frame of the game
- **Galaga**: Doesn't work because 8x16 sprites are not yet supported

PPU & rendering issues:

- PPUSCROLL & PPUADDR sharing internal registers is not handled correctly
- Sprite 0 hit is only partially implemented:
	- It works if you assume no background pixels are transparent
	- It does not factor in some of the weird quirks
	- It's only line-accurate, not cycle-accurate
- Background priority isn't implemented
- Right now we only render once at the start of VBLANK, so mid-frame updates won't work
- We don't limit to max 8 sprites per line
	- This might sound like a limit we don't want, but some games actually use this intentionally (like doors in The Legend of Zelda)
	- Sprite overflow flag is not set either (which some games might depend on)
- Scrolling is implemented, but not well tested since the only ROMs I'm testing don't use scrolling
- Exact behavior when updating PPU outside of VBLANK is not fully emulated
- 8x16 sprites are not yet supported

Next goals:

- Fix controller implementation
- Split-screen rendering, to support mid-frame updates
- Code cleanups
- Other PPU features & behaviors
- Basic APU emulation (without actually playing audio yet - just show audio channel info on-screen)

Lower priority stuff:

- Player 2 controller support

Future goals:

- Emulate Super Mario Bros

Stretch goals:

- Emulate Mega Man 2
- Emulate The Legend of Zelda

### Other related ideas

Try to emulate as much of the PPU behavior on the GPU as possible

Take a ROM disassembly and JIT compile it into something which can be emulated much more efficiently

Taking a ROM disassembly and converting it into C/C++ code which can then be compiled natively

- No, I don't mean converting it into code which can be compiled into the same assembly - but rather, functionally equivalent code
- I also wouldn't expect this to be nice clean readable code
- Similar to what was reportedly done for the original Mega Man Legacy Collection

Write my own disassembler
