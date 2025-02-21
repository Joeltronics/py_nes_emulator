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

		self._controller_1_shift_register: uint8 = 0
		self._controller_2_shift_register: uint8 = 0

		self._out0: bool = False

	def set_button(self, button: Button, pressed: bool, player: int = 1) -> None:

		bit_mask = 1 << int(button)

		if player == 1:
			if pressed:
				self._controller_1_state |= bit_mask
			else:
				self._controller_1_state &= ~bit_mask
			logger.debug(f'Player 1, Button: {button.name}, Pressed: {pressed}, State: {self._controller_1_state:08b}')

		elif player == 2:
			if pressed:
				self._controller_2_state |= bit_mask
			else:
				self._controller_2_state &= ~bit_mask
			logger.debug(f'Player 2, Button: {button.name}, Pressed: {pressed}, State: {self._controller_2_state:08b}')

		else:
			raise ValueError('Player must be 1 or 2')

	def write_register_4016_from_cpu(self, value: uint8) -> None:

		out0_new = bool(value & 1)

		if self._out0 and not out0_new:
			self._controller_1_shift_register = self._controller_1_state
			self._controller_2_shift_register = self._controller_2_state

		self._out0 = out0_new

		logger.debug(f'Value: 0x{value:02X}, Controller 1: {self._controller_1_state:08b}, Controller 2: {self._controller_2_state:08b}')

	def read_register_from_cpu(self, addr: pointer16) -> uint8:

		match addr:
			case 0x4016:
				ret = self._controller_1_shift_register & 1
				self._controller_1_shift_register = (self._controller_1_shift_register >> 1) | 0b1000_0000

			case 0x4017:
				ret = self._controller_2_shift_register & 1
				self._controller_2_shift_register = (self._controller_2_shift_register >> 1) | 0b1000_0000

			case _:
				raise ValueError(f'Invalid controller register: {addr}')

		return ret
