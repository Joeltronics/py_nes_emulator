# py_nes_emulator
NES emulator written in Python

This is just a toy example to learn about emulator development - optimization isn't really the goal, so I don't expect this Python version will ever be performant enough to actually play games in real-time (though I may eventually port this to C, C++, or Rust).

My main goal is to get this to the point where it can emulate Super Mario Bros - and with it, most mapper 0 games. Though not necessarily in real time (see next section...)

### Probably Out of scope

**Being optimized enough to actually play games in real-time.** That's not to say there won't be any optimization (for example, I'm interested in trying to do some of the PPU emulation on GPU), but Python really isn't intended for emulating a few million CPU & PPU instructions per second. Not to say it isn't possible - but it would need aggressively optimized code, at the expense of readability, maintainability, and "pythonic"-ness.

**Perfect emulation.** For example, precise cycle accuracy, hardware quirks like open-bus behavior, or pixel-exact PPU emulation. I do expect to support some of the most common quirks that many games rely on, but definitely not Battletoads-level accuracy.

**Audio.** I love audio coding, but Python isn't the right language for real-time audio either (and the purist in me would hate to just your system's built-in MIDI)

### Current status

Emulation is basic, and there's no controller input yet. The Donkey Kong, Ice Climber, and Balloon Fight title screens can all emulate, including Balloon Fight's attract mode. There's also no APU or mapper support.

PPU & rendering issues:

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
- Exact behavior of updating PPU outside of VBLANK is not fully emulated

Next goals:

- Controller support
- Code cleanups
- Mid-frame updates
- Other PPU features & behaviors

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
