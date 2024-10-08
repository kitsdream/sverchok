# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import bpy
from sverchok.utils.modules.drawing_abstractions import drawing 


SpaceView3D = bpy.types.SpaceView3D

callback_dict = {}


def tag_redraw_all_3dviews():

    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        region.tag_redraw()


def callback_enable(*args, overlay='POST_VIEW'):
    n_id = args[0]
    if n_id in callback_dict:
        return

    handle_pixel = SpaceView3D.draw_handler_add(draw_callback_px, args, 'WINDOW', overlay)
    callback_dict[n_id] = handle_pixel
    tag_redraw_all_3dviews()


def callback_disable(n_id):
    handle_pixel = callback_dict.get(n_id, None)
    if not handle_pixel:
        return
    SpaceView3D.draw_handler_remove(handle_pixel, 'WINDOW')
    del callback_dict[n_id]
    tag_redraw_all_3dviews()


def callback_disable_all():
    temp_list = list(callback_dict.keys())
    for n_id in temp_list:
        if n_id:
            callback_disable(n_id)


def restore_opengl_defaults():
    drawing.reset_line_width()
    drawing.disable_blendmode()
    drawing.disable_depth_test()

    # glIsEnabled with argument 
    # GL_POLYGON_OFFSET_FILL, 
    # GL_POLYGON_OFFSET_LINE, or 
    # GL_POLYGON_OFFSET_POINT.

    # glGet with argument 
    # GL_POLYGON_OFFSET_FACTOR or 
    # GL_POLYGON_OFFSET_UNITS.


def draw_callback_px(n_id, data):
    context = bpy.context
    drawing_func = data.get('custom_function')   # must accept 'context' first
    args = data.get('args', (None,))             # args does not need to be a tuple.
    drawing.enable_depth_test()
    drawing_func(context, args)
    restore_opengl_defaults()

    ###
    #    in your drawing function you can use the first parameter to get a reference to region/3d
    #
    #    region = context.region
    #    region3d = context.space_data.region_3d
    ###


def unregister():
    callback_disable_all()
