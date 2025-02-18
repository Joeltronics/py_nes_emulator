#!/usr/bin/env python3

import logging
import pygame
import pygame.freetype
from typing import Final

from nes.controllers import Controllers, Button
from nes.renderer import Renderer
from nes.graphics_utils import array_to_surface


logger = logging.getLogger(__name__)


# TODO: Load key bindings from file
KEY_BINDINGS: dict = {
	pygame.K_w: Button.up,
	pygame.K_a: Button.left,
	pygame.K_s: Button.down,
	pygame.K_d: Button.right,
	pygame.K_j: Button.a,
	pygame.K_k: Button.b,
	pygame.K_RSHIFT: Button.select,
	pygame.K_RETURN: Button.start,
}


FPS_TEXT_FONT_SIZE: Final[int] = 18


class Ui:
	def __init__(self, controllers: Controllers, renderer: Renderer):

		self.running = False

		pygame.init()

		self.controllers = controllers
		self.renderer = renderer

		self.screen = pygame.display.set_mode((128 + 512 + 512, 480 + 256 + 8))

		self.font = pygame.freetype.SysFont(
			pygame.freetype.get_default_font(),
			FPS_TEXT_FONT_SIZE, bold=False, italic=False)

		self.chr_surf = array_to_surface(self.renderer.get_chr_im())
		self.current_palette_surf = array_to_surface(self.renderer.get_current_palettes_debug_im(), 8)
		self.full_palette_surf = array_to_surface(self.renderer.get_full_palette_debug_im(), 8)
		self.nametable_surf = array_to_surface(self.renderer.get_nametables_debug_im())
		self.sprite_layer_surf = array_to_surface(self.renderer.get_sprite_layer_debug_im())
		self.sprites_surf = array_to_surface(self.renderer.get_sprites_debug_im(), 2)
		self.frame_surf = array_to_surface(self.renderer.get_frame_im(), 2)

		pygame.display.set_caption('NES Emulator')

		info = pygame.display.Info()
		logging.info(f'Display info:\n{info}')

		self.screen.fill((0, 0, 0))
		self.screen.blit(self.chr_surf, (0, 0))
		pygame.display.flip()

		self.running = True

	def draw(self, fps_str: str = '') -> None:

		self.screen.fill((0, 0, 0))

		self.screen.blit(self.chr_surf, (0, 0))

		array_to_surface(self.renderer.get_current_palettes_debug_im(), 8, into=self.current_palette_surf)
		self.screen.blit(self.current_palette_surf, (0, 256))

		array_to_surface(self.renderer.get_full_palette_debug_im(), 8, into=self.full_palette_surf)
		self.screen.blit(self.full_palette_surf, (0, 256 + 16))

		array_to_surface(self.renderer.get_nametables_debug_im(), into=self.nametable_surf)
		self.screen.blit(self.nametable_surf, (128 + 512, 0))

		array_to_surface(self.renderer.get_sprite_layer_debug_im(), into=self.sprite_layer_surf)
		self.screen.blit(self.sprite_layer_surf, (128 + 512, 480))

		array_to_surface(self.renderer.get_sprites_debug_im(), 2, into=self.sprites_surf)
		self.screen.blit(self.sprites_surf, (128 + 512 + 256 + 8, 480))

		array_to_surface(self.renderer.get_frame_im(), 2, into=self.frame_surf)
		self.screen.blit(self.frame_surf, (128, 0))

		if fps_str:
			lines = fps_str.splitlines()
			for idx, line in enumerate(reversed(lines)):
				self.font.render_to(
					self.screen,
					(0, 480 + 256 + 8 - FPS_TEXT_FONT_SIZE * (idx + 1)),
					line,
					(255, 0, 0))
			# self.font.render_to(self.screen, (0, 480 + 256 + 8 - FPS_TEXT_FONT_SIZE * len(lines)), fps_str, (255, 0, 0))

	def flip(self):
		pygame.display.flip()

	def handle_events(self) -> None:
		for event in pygame.event.get():
			match event.type:
				case pygame.QUIT:
					logger.info('Received pygame.QUIT event')
					self.running = False
				case pygame.KEYDOWN | pygame.KEYUP:
					self._handle_key(event)

	def _handle_key(self, event):
		button = KEY_BINDINGS.get(event.key)
		if button is not None:
			down = (event.type == pygame.KEYDOWN)
			self.controllers.set_button(button, down)
