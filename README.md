# py_nes_emulator
NES emulator written in Python

This is just a toy example to learn about emulator development - optimization isn't really the goal, so I don't expect this Python version will ever be performant enough to actually play games in real-time (though I may eventually port this to C, C++, or Rust).

My main goal is to get this to the point where it can emulate Super Mario Bros - and with it, most mapper 0 games. Though not necessarily in real time (see next section...)

### Probably Out of scope

**Being optimized enough to actually play games in real-time.** That's not to say there won't be any optimization (for example, I'm interested in trying to do some of the PPU emulation on GPU), but Python really isn't intended for emulating a few million CPU & PPU instructions per second. Not to say it isn't possible - but it would need aggressively optimized code, at the expense of readability, maintainability, and "pythonic"-ness.

**Perfect emulation.** For example, precise cycle accuracy, hardware quirks like open-bus behavior, or pixel-exact PPU emulation. I do expect to support some of the most common quirks that many games rely on, but definitely not Battletoads-level accuracy.

**Audio.** I love audio coding, but Python isn't the right language for real-time audio either (and the purist in me would hate to just your system's built-in MIDI)

### Current status

Very little yet. All documented CPU instructions are emulated (at least in theory - not all are tested), and basic there's basic PPU functionality. But otherwise:

- No graphics are being rendered at all yet
- No controller input
- No APU

Balloon Fight seems to run without crashing (though it's hard to tell if it's actually emulating properly without graphics). Donkey Kong & Ice Climber both crash from hitting an invalid instruction immediately after an RTS call, so there seems to be a problem with one of the stack-related instructions.

Next goals:

- Fix the bug causing Donkey Kong & Ice Climber to crash
- Basic graphics implementation
- Emulate some simpler ROMS (Balloon Fight, Donkey Kong, Ice Climber)

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
