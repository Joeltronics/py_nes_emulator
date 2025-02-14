#!/usr/bin/env python3

import logging
import pygame

from nes.renderer import Renderer
from nes.graphics_utils import array_to_surface, upscale


logger = logging.getLogger(__name__)


class Ui:
	def __init__(self, renderer: Renderer):

		self.running = False
		self.renderer = renderer

		self.screen = pygame.display.set_mode((128 + 512 + 512, 480 + 256 + 8))

		chr_surf = array_to_surface(self.renderer.get_chr_im())
		self.screen.blit(chr_surf, (0, 0))

		pygame.display.set_caption('NES Emulator') 

		# background_colour = (0, 0, 0)
		# self.screen.fill(background_colour)
		pygame.display.flip()

		self.running = True

	def draw(self):

		current_palette = array_to_surface(self.renderer.get_current_palettes_debug_im(), 8)
		self.screen.blit(current_palette, (0, 256))

		full_palette = array_to_surface(self.renderer.get_full_palette_debug_im(), 8)
		self.screen.blit(full_palette, (0, 256 + 16))

		nametable = array_to_surface(self.renderer.get_nametables_debug_im())
		self.screen.blit(nametable, (128 + 512, 0))

		sprite_layer = array_to_surface(self.renderer.get_sprite_layer_debug_im())
		self.screen.blit(sprite_layer, (128 + 512, 480))

		sprites = array_to_surface(self.renderer.get_sprites_debug_im(), 2)
		self.screen.blit(sprites, (128 + 512 + 256 + 8, 480))

		frame = array_to_surface(self.renderer.get_frame_im(), 2)
		self.screen.blit(frame, (128, 0))

		pygame.display.flip()

	def handle_events(self):
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				logger.info('Received pygame.QUIT event')
				self.running = False
