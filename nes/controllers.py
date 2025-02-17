#!/usr/bin/env python3

from enum import IntEnum, unique
import logging

from nes.types import uint8, pointer16


logger = logging.getLogger(__name__)


@unique
class Button(IntEnum):
	a      = 0
	b      = 1
	select = 2
	start  = 3
	up     = 4
	down   = 5
	left   = 6
	right  = 7


class Controllers:
	def __init__(self):
		self._controller_1_state: uint8 = 0
		self._controller_2_state: uint8 = 0

		self._latch_bit: uint8 = 0

	def set_button(self, button: Button, pressed: bool, player: int = 1) -> None:

		logger.info(f'Player {player}, Button: {button.name}, Pressed: {pressed}')

		bit_mask = 1 << int(button)

		if player == 1:
			if pressed:
				self._controller_1_state |= bit_mask
			else:
				self._controller_1_state &= ~bit_mask

		elif player == 2:
			if pressed:
				self._controller_2_state |= bit_mask
			else:
				self._controller_2_state &= ~bit_mask

		else:
			raise ValueError('Player must be 1 or 2')

	def write_register_4016_from_cpu(self, value: uint8) -> None:
		# TODO accuracy: Actually use value here, for proper emulation
		self._latch_bit = 1
		logger.debug(f'Value: 0x{value:02X}, Controller 1: {self._controller_1_state:08b}, Controller 2: {self._controller_2_state:08b}')

	def read_register_from_cpu(self, addr: pointer16) -> uint8:
		if addr == 0x4016:

			if self._latch_bit > 0b1000_0000:
				return 1

			ret = int(bool(self._controller_1_state & self._latch_bit))

			logger.debug(f'Controller state {self._controller_1_state:08b} & latch {self._latch_bit:08b} = ret {ret}')

			self._latch_bit <<= 1
			return ret

		if addr == 0x4017:

			if self._latch_bit > 0b1000_0000:
				return 1

			ret = int(bool(self._controller_2_state & self._latch_bit))
			self._latch_bit <<= 1
			return ret

		raise ValueError(f'Invalid controller register: {addr}')
