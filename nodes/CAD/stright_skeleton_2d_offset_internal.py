# This file is part of project Sverchok. It's copyrighted by the contributors
# recorded in the version control history of the file, available from
# its original location https://github.com/nortikin/sverchok/commit/master
#
# SPDX-License-Identifier: GPL3
# License-Filename: LICENSE


import bpy
from concurrent.futures import ThreadPoolExecutor

import collections
import itertools
import numpy as np
import bpy, math, bmesh
from bpy.props import FloatProperty, BoolProperty, IntProperty, EnumProperty
from mathutils import Vector, Matrix

from sverchok.node_tree import SverchCustomTreeNode
from sverchok.data_structure import updateNode
from sverchok.utils.geom_2d.merge_mesh import merge_mesh
from sverchok.utils.nodes_mixins.sockets_config import ModifierLiteNode
from sverchok.data_structure import dataCorrect, updateNode, zip_long_repeat, ensure_nesting_level, flatten_data
from sverchok.ui.sv_icons import custom_icon
from sverchok.utils.sv_bmesh_utils import bmesh_from_pydata
from sverchok.nodes.analyzer.mesh_filter import Edges
from sverchok.nodes.vector.vertices_sort import sort_vertices_by_connexions
from sverchok.utils.modules.polygon_utils import areas_from_polygons
from sverchok.utils.sv_operator_mixins import SvGenericNodeLocator
from .stright_skeleton_2d_extrude import create_list2_in_range

enable_module = False
try:
    from more_itertools import sort_together
    import pySVCGAL
    from pySVCGAL.pySVCGAL import pySVCGAL_straight_skeleton_2d_offset
    enable_module = True
except ModuleNotFoundError:
    enable_module = False



def vertices_sort_by_edges(verts_in, edges_in):
    edges_indexes = list(itertools.chain(*edges_in))
    verts_out = []
    if len(edges_indexes)==0:
        pass
    else:
        edges_indexes_0 = edges_indexes[ ::2]
        edges_indexes_1 = edges_indexes[1::2]

        chain = []
        pos = 0
        v0_idx = edges_indexes_0[pos]
        chain.append(v0_idx)
        
        # Build Cchain to the right
        while True:
            v1_idx = edges_indexes_1[pos]
            if v1_idx in chain:
                # Break circle
                break
            chain.append(v1_idx)
            if v1_idx in edges_indexes_0:
                pos = edges_indexes_0.index(v1_idx)
            else:
                # End of edjes
                break

        # Build Chain to the left
        # Попробовать построить цепочку в обратном направлении (тут не в курсе, вышли из-за кольца
        # или что достигнут конец цепочки:	
        
        v1_idx = chain[0]
        if v1_idx not in edges_indexes_1:
            pass
        else:
            pos = edges_indexes_1.index( v1_idx )
            while True:
                v0_idx = edges_indexes_0[pos]
                if v0_idx in chain:
                    # Circle
                    break
                chain.append(v0_idx)
                if v0_idx in edges_indexes_1:
                    pos = edges_indexes_1.index(v0_idx)
                else:
                    # End of circle
                    # конец цепочки
                    break
        
        np_verts = np.array(verts_in)
        verts_out = np_verts[chain].tolist()
    return verts_out
    pass

def separate_loose_mesh(verts_in, poly_edge_in):
        ''' separate a mesh by loose parts.
        input:
          1. list of verts
          2. list of edges/polygons
        output: list of
          1. separated list of verts
          2. separated list of edges/polygons with new indices of separated elements
          3. separated list of edges/polygons (like 2) with old indices
        '''
        verts_out = []
        poly_edge_out = []
        poly_edge_old_indexes_out = []  # faces with old indices 

        # build links
        node_links = {}
        for edge_face in poly_edge_in:
            for i in edge_face:
                if i not in node_links:
                    node_links[i] = set()
                node_links[i].update(edge_face)

        nodes = set(node_links.keys())
        n = nodes.pop()
        node_set_list = [set([n])]
        node_stack = collections.deque()
        node_stack_append = node_stack.append
        node_stack_pop = node_stack.pop
        node_set = node_set_list[-1]
        # find separate sets
        while nodes:
            for node in node_links[n]:
                if node not in node_set:
                    node_stack_append(node)
            if not node_stack:  # new mesh part
                n = nodes.pop()
                node_set_list.append(set([n]))
                node_set = node_set_list[-1]
            else:
                while node_stack and n in node_set:
                    n = node_stack_pop()
                nodes.discard(n)
                node_set.add(n)
        # create new meshes from sets, new_pe is the slow line.
        if len(node_set_list) >= 1:
            for node_set in node_set_list:
                mesh_index = sorted(node_set)
                vert_dict = {j: i for i, j in enumerate(mesh_index)}
                new_vert = [verts_in[i] for i in mesh_index]
                new_pe = [[vert_dict[n] for n in fe]
                            for fe in poly_edge_in
                            if fe[0] in node_set]
                old_pe = [fe for fe in poly_edge_in
                             if fe[0] in node_set]
                verts_out.append(new_vert)
                poly_edge_out.append(new_pe)
                poly_edge_old_indexes_out.append(old_pe)
        elif node_set_list:  # no reprocessing needed
            verts_out.append(verts_in)
            poly_edge_out.append(poly_edge_in)
            poly_edge_old_indexes_out.append(poly_edge_in)

        return verts_out, poly_edge_out, poly_edge_old_indexes_out

def ShowMessageBox(message = "", title = "Message Box", icon = 'INFO'):
    def draw(self, context):
        self.layout.label(text=message)
    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)


# Operator to save data in .dat format file for test in CGAL (Hidden in production)
class SvSaveCGALDatFile(bpy.types.Operator, SvGenericNodeLocator):
    ''' Save coords and angles to the file .dat for CGAL '''
    bl_idname = "node.sverchok_save_cgal_dat_file"
    bl_label = "Save coords and angles to the file .dat for CGAL"
    
    def sv_execute(self, context, node):
        if hasattr(node, 'saveCGALDatFile')==True:
            node.saveCGALDatFile()
            #text = node.dataAsString()
            #context.window_manager.clipboard = text
            ShowMessageBox("File saved")
        pass

# Привести параметры и интерфейс в соответствии с CGAL
class SvStraightSkeleton2DOffset(ModifierLiteNode, SverchCustomTreeNode, bpy.types.Node):
    """
    Triggers: Merge two 2d meshes

    Each mesh can have disjoint parts
    Only X and Y coordinate takes in account
    """
    bl_idname = 'SvStraightSkeleton2DOffset'
    bl_label = 'Straight Skeleton 2D Offset (Alpha)'
    bl_icon = 'MOD_OUTLINE'

    sv_dependencies = ['pySVCGAL', 'more_itertools']

    def wrapper_tracked_ui_draw_op(self, layout_element, operator_idname, **keywords):
        """
        this wrapper allows you to track the origin of a clicked operator, by automatically passing
        the node_name and tree_name to the operator.

        example usage:

            row.separator()
            self.wrapper_tracked_ui_draw_op(row, "node.view3d_align_from", icon='CURSOR', text='')

        """
        op = layout_element.operator(operator_idname, **keywords)
        op.node_name = self.name
        op.tree_name = self.id_data.name
        return op

    offset_modes = [
            ('OBJECT_ALL_OFFSETS', "All", "Every object get all offsets", 'THREE_DOTS', 0),
            ('OBJECT_ONE_OFFSET' , "One", "Every object get one offset", 'DECORATE', 1),
        ]
    offset_mode : EnumProperty(
        name = "Offset mode",
        default = 'OBJECT_ALL_OFFSETS',
        description = "How many offsets per object (One or All)",
        items = offset_modes,
        update = updateNode
        ) # type: ignore

    ss_offset1: FloatProperty(
        name="Offsets   ",
        default=0.1,
        description = "Offsets",
        update=updateNode,
        #subtype='DISTANCE',
    ) # type: ignore


    altitude_modes = [
            ('OBJECT_ALL_ALTITUDES', "All", "Every object get all altitudes", 'THREE_DOTS', 0),
            ('OBJECT_ONE_ALTITUDE' , "One", "Every object get one altitude", 'DECORATE', 1),
        ]
    altitude_mode : EnumProperty(
        name = "Altitudes",
        default = 'OBJECT_ALL_ALTITUDES',
        description = "How many Altitudes per object (One or All)",
        items = altitude_modes,
        update = updateNode
        ) # type: ignore


    ss_altitude1: FloatProperty(
        name="Altitudes",
        default=1, 
        description = "Altitude of offsets",
        update=updateNode,
        #subtype='DISTANCE',
    ) # type: ignore

    ss_shapes_modes = [
            (          'FULL_MODE',          "Full mode", "Extrude full shape (outer contours with holes)", 'RENDER_ANIMATION', 0),
            (      'EXCLUDE_HOLES',      "Exclude Holes", "Keep only outer boundary", 'SELECT_EXTEND', 1),
            (  'INVERT_HOLES_SOFT',  "Invert Holes Soft", "Exclude outer boundary and fill holes. If outer boundary has no holes then keep outer boundary.", 'SELECT_INTERSECT', 2),
            (  'INVERT_HOLES_HARD',  "Invert Holes Hard", "Exclude outer boundary and Fill holes. If Outer Boundary has no holes then shape removed", 'SNAP_VERTEX', 3),
        ]
    ss_shapes_mode1 : EnumProperty(
        name = "Shapes mode",
        description = "0-Full mode (outer contour and holes), 1-only outer contours, 2-Extrude holes as boundary, exclude outer boundary)",
        items = ss_shapes_modes,
        default = 'FULL_MODE',
        update = updateNode
        ) # type: ignore



    only_tests_for_valid: BoolProperty(
        name="Only tests",
        description='Test all shapes are valid (safe time before start skeleton if meshes are highpoly)',
        default=False, update=updateNode) # type: ignore

    force_z_zero: BoolProperty(
        name="Force z=0.0",
        description='Force z=0.0 on any value',
        default=False, update=updateNode) # type: ignore

    verbose_messages_while_process: BoolProperty(
        name='Verbose',
        description='Show additional debug info in console',
        default=True, update=updateNode) # type: ignore

    # contours_or_mesh: BoolProperty(
    #     name='Ret',
    #     description='off - contours, on - mesh',
    #     default=True, update=updateNode) # type: ignore

    join_modes = [
            ('SPLIT', "Split", "Separate the result meshes into individual meshes", 'SNAP_VERTEX', 0),
            ('KEEP' , "Keep", "Keep as source meshes", 'SYNTAX_ON', 1),
            ('MERGE', "Merge", "Join all results meshes into a single mesh", 'STICKY_UVS_LOC', 2)
        ]

    join_mode : EnumProperty(
        name = "Output mode",
        items = join_modes,
        default = 'KEEP',
        update = updateNode) # type: ignore

    res_types = [
            ('CONTOURS', "Contours", "Edges of contours", 'SNAP_VERTEX', 0),
            ('FACES' , "Faces", "Fill faces", 'SYNTAX_ON', 1),
        ]

    res_type : EnumProperty(
        name = "Result",
        items = res_types,
        default = 'FACES',
        update = updateNode) # type: ignore

    objects_mask_modes = [
            ('BOOLEANS', "Booleans", "Boolean values (0/1) as mask of Voronoi Sites per objects [[0,1,0,0,1,1],[1,1,0,0,1],...]. Has no influence if socket is not connected (All sites are used)", 0),
            ('INDEXES', "Indexes", "Indexes as mask of Voronoi Sites per objects [[1,2,0,4],[0,1,4,5,7],..]. Has no influence if socket is not connected (All sites are used)", 1),
        ]
    objects_mask_mode : EnumProperty(
        name = "Mask of Objects",
        items = objects_mask_modes,
        default = 'BOOLEANS',
        update = updateNode
        ) # type: ignore
    objects_mask_inversion : BoolProperty(
        name = "Invert",
        default = False,
        description="Invert mask of sites. Has no influence if socket is not connected (All sites are used)",
        update = updateNode) # type: ignore

    def draw_vertices_out_socket(self, socket, context, layout):
        layout.prop(self, 'join_mode', text='')
        if socket.is_linked:  # linked INPUT or OUTPUT
            layout.label(text=f"{socket.label}. {socket.objects_number or ''}")
        else:
            layout.label(text=f'{socket.label}')
        pass

    def draw_failed_contours_vertices_out_socket(self, socket, context, layout):
        if socket.objects_number>0:
            layout.label(text=f'', icon='ERROR')
        layout.label(text=f'{socket.label} ')
        if socket.is_linked:  # linked INPUT or OUTPUT
            layout.label(text=f". {socket.objects_number or ''}")
        elif socket.is_output:  # unlinked OUTPUT
            layout.separator()

    def updateMaskMode(self, context):
        if self.objects_mask_mode=='BOOLEANS':
            self.inputs["objects_mask"].label = "Mask of Objects"
        elif self.objects_mask_mode=='INDEXES':
            self.inputs["objects_mask"].label = "Indexes of Objects"
        updateNode(self, context)

    def draw_ss_shapes_modes_in_socket(self, socket, context, layout):
        grid = layout.grid_flow(row_major=False, columns=3, align=True)
        col = grid.row(align=True)
        if socket.is_linked:
            socket_label = socket.objects_number if hasattr(socket, "objects_number")==True else '-'
            col.label(text=f"Shapes mode {socket_label}")
        else:
            col.prop(self, 'ss_shapes_mode1', text='Shapes mode')
        pass

    def draw_objects_mask_in_socket(self, socket, context, layout):
        grid = layout.grid_flow(row_major=True, columns=2)
        if not socket.is_linked:
            grid.enabled = False
        col2 = grid.column()
        col2_row1 = col2.row()
        col2_row1.alignment='LEFT'
        if socket.is_linked:
            col2_row1.label(text=f"Mask of Objects. {socket.objects_number or ''}:")
        else:
            col2_row1.label(text=f"Mask of Objects:")
        col2_row2 = col2.row()
        col2_row2.alignment='LEFT'
        col2_row2.column(align=True).prop(self, "objects_mask_inversion")
        col3 = grid.column()
        col3.prop(self, "objects_mask_mode", expand=True)

    def draw_offset_mode_in_socket(self, socket, context, layout):
        grid = layout.grid_flow(row_major=False, columns=3, align=True)
        col = grid.column() # align=True
        col.prop(self, 'ss_offset1')
        if socket.is_linked==True:
            col.enabled = False
        else:
            col.enabled = True
        grid.prop(self, 'offset_mode', expand=True, icon_only=True) 

    def draw_altitude_mode_in_socket(self, socket, context, layout):
        grid = layout.grid_flow(row_major=False, columns=3, align=True)
        col = grid.column()
        col.prop(self, 'ss_altitude1')
        if socket.is_linked==True:
            col.enabled = False
        else:
            col.enabled = True
        grid.prop(self, 'altitude_mode', expand=True, icon_only=True) 

    def draw_buttons(self, context, layout):
        col = layout.column()
        col.row(align=True).prop(self, 'res_type', expand=True)
        col.prop(self, 'only_tests_for_valid')
        col.prop(self, 'force_z_zero')
        col.prop(self, 'verbose_messages_while_process') 
        #col.row().prop(self, 'join_mode', expand=True)
        #ui_file_save_dat = col.row()
        #self.wrapper_tracked_ui_draw_op(ui_file_save_dat, SvSaveCGALDatFile.bl_idname, text='', icon='DISK_DRIVE')
        
        pass

    def draw_buttons_ext(self, context, layout):
        col = layout.column(align=True)
        pass

    def sv_init(self, context):

        self.width = 180

        self.inputs.new('SvVerticesSocket', 'vertices')
        self.inputs.new('SvStringsSocket' , 'edges')
        self.inputs.new('SvStringsSocket' , 'polygons')
        self.inputs.new('SvStringsSocket' , 'ss_shapes_modes')
        self.inputs.new('SvStringsSocket' , 'ss_offsets').prop_name = 'ss_offset1'
        self.inputs.new('SvStringsSocket' , 'ss_altitudes').prop_name = 'ss_altitude1'
        self.inputs.new('SvStringsSocket' , 'objects_mask').label = "Mask of Objects"
        self.inputs.new('SvTextSocket'    , 'file_name')

        self.inputs['vertices'].label = 'Vertices'
        self.inputs['edges'].label = 'Edges'
        self.inputs['polygons'].label = 'Polygons'
        self.inputs['ss_shapes_modes'].custom_draw = 'draw_ss_shapes_modes_in_socket'
        self.inputs['ss_offsets'].label = 'Offsets'
        self.inputs['ss_offsets'].custom_draw = 'draw_offset_mode_in_socket'
        self.inputs['ss_altitudes'].label = 'Offsets'
        self.inputs['ss_altitudes'].custom_draw = 'draw_altitude_mode_in_socket'
        self.inputs['objects_mask'].custom_draw = 'draw_objects_mask_in_socket'
        self.inputs['file_name'].label = 'File Name'
        self.inputs['file_name'].hide = True

        self.outputs.new('SvVerticesSocket', 'vertices')
        self.outputs.new('SvStringsSocket' , 'edges')
        self.outputs.new('SvStringsSocket' , 'polygons')
        self.outputs.new('SvStringsSocket' , 'offsets')
        self.outputs.new('SvStringsSocket' , 'altitudes')
        self.outputs.new('SvVerticesSocket', 'failed_contours_vertices')

        self.outputs['vertices'].label = 'Vertices'
        self.outputs['vertices'].custom_draw = 'draw_vertices_out_socket'
        self.outputs['edges'].label = 'Edges'
        self.outputs['polygons'].label = 'Polygons'
        self.outputs['offsets'].label = 'Offsets'
        self.outputs['altitudes'].label = 'Altitudes'
        self.outputs['failed_contours_vertices'].label = 'Wrong contours verts'
        self.outputs['failed_contours_vertices'].custom_draw = 'draw_failed_contours_vertices_out_socket'

    def process(self):
        if not all([sock.is_linked for sock in self.inputs if sock.name in ['vertices', 'edges', 'polygons'] ]):
            return
        if not any([sock.is_linked for sock in self.outputs]):
            return
        
        inputs = self.inputs
        _Vertices  = inputs['vertices'].sv_get(default=[[]], deepcopy=False)
        Vertices3  = ensure_nesting_level(_Vertices, 3)
        _Edges     = inputs['edges'].sv_get(default=[[]], deepcopy=False)
        Edges3     = ensure_nesting_level(_Edges, 3)
        _Faces     = inputs['polygons'].sv_get(default=[[]], deepcopy=False)
        Faces3     = ensure_nesting_level(_Faces, 3)
        _ss_offsets  = inputs['ss_offsets'].sv_get(default=[[self.ss_offset1]], deepcopy=False)
        ss_offsets2  = ensure_nesting_level(_ss_offsets, 2)
        _ss_altitudes  = inputs['ss_altitudes'].sv_get(default=[[self.ss_altitude1]], deepcopy=False)
        ss_altitudes2  = ensure_nesting_level(_ss_altitudes, 2)

        # selecte shape mode in property
        ss_shapes_mode1 = [I for I, shapes_modes in enumerate(self.ss_shapes_modes) if shapes_modes[0] == self.ss_shapes_mode1]
        if len(ss_shapes_mode1)>0:
            ss_shapes_mode1 = ss_shapes_mode1[0]
        else:
            ss_shapes_mode1 = 0
        _ss_shapes_modes  = inputs['ss_shapes_modes'].sv_get(default=[[ss_shapes_mode1]], deepcopy=False)
        ss_shapes_mode2  = ensure_nesting_level(_ss_shapes_modes, 2)[0]

        _objects_mask_in = inputs['objects_mask'].sv_get(default=[[]], deepcopy=False)
        objects_mask_in = ensure_nesting_level(_objects_mask_in, 2)[0]

        _file_names = inputs['file_name'].sv_get(default=[[]], deepcopy=False)
        file_names3 = ensure_nesting_level(_file_names, 3)
        file_name_dat = None
        if len(file_names3)>0 and len(file_names3[0])>0 and len(file_names3[0][0])>0:
            file_name_dat = file_names3[0][0][0]

        res_verts = []
        res_boundaries_verts = []
        res_edges = []
        res_faces = []
        res_offsets = []   # what offset used for results objects
        res_altitudes = [] # what altitude used for results objects

        objects_data = dict()
        objects_offsets_of_boundaries = []
        objects_area_boundaries = []

        contours_failed_at_all = []
        params = zip_long_repeat(Vertices3, Edges3, Faces3)

        len_vertices3 = len(Vertices3)
        np_mask = np.zeros(len_vertices3, dtype=bool)
        if self.inputs['objects_mask'].is_linked:
            if self.objects_mask_mode=='BOOLEANS':
                for I in range(len_vertices3):
                    if I<len(objects_mask_in):
                        np_mask[I] = objects_mask_in[I]
                    else:
                        np_mask[I] = objects_mask_in[-1]
                pass
            elif self.objects_mask_mode=='INDEXES':
                for I in range(len(objects_mask_in)):
                    objects_mask_in_I = objects_mask_in[I]
                    if -len_vertices3 < objects_mask_in_I < len_vertices3:
                        np_mask[objects_mask_in[I]] = True
                        pass
                    pass
                pass
            if self.objects_mask_inversion==True:
                np_mask = np.invert(np_mask)
            pass
        objects_mask = np_mask.tolist()

        _shapes_modes = create_list2_in_range(len_vertices3, ss_shapes_mode2, [shapes_modes[-1] for I, shapes_modes in enumerate(self.ss_shapes_modes)])
        allowed_shapes_modes = [shapes_modes[-1] for I, shapes_modes in enumerate(self.ss_shapes_modes)] # for ensurence for developers. Will not work in production mode.

        for I, (verts_i, edges_i, faces_i) in enumerate( params ):
            mask = objects_mask[I]
            if mask==True:
                continue

            if self.offset_mode=='OBJECT_ALL_OFFSETS':
                if I<=len(ss_offsets2)-1:
                    ss_offsets = ss_offsets2[I]
                else:
                    ss_offsets = ss_offsets2[-1]
                pass
            elif self.offset_mode=='OBJECT_ONE_OFFSET':
                if I<=len(ss_offsets2[0])-1:
                    ss_offsets = [ss_offsets2[0][I]]
                else:
                    ss_offsets = [ss_offsets2[0][-1]]
                pass
            
            if self.altitude_mode=='OBJECT_ALL_ALTITUDES':
                if I<=len(ss_altitudes2)-1:
                    ss_altitudes = ss_altitudes2[I]
                else:
                    ss_altitudes = ss_altitudes2[-1]
                pass
            elif self.altitude_mode=='OBJECT_ONE_ALTITUDE':
                if I<=len(ss_altitudes2[0])-1:
                    ss_altitudes = [ss_altitudes2[0][I]]
                else:
                    ss_altitudes = [ss_altitudes2[0][-1]]
                pass
            
            if _shapes_modes[I]<0 or len(self.ss_shapes_modes) < _shapes_modes[I]:
                raise Exception(f"unknown Shapes mode value: '{_shapes_modes[I]}'. Allowed values [{allowed_shapes_modes}]")
            
            shapes_mode_1 = self.ss_shapes_modes[ _shapes_modes[I] ][0]

            # separate objects of loose parts (objects can has islands. Every island have to be separated)
            if not faces_i or not faces_i[0]:
                raise Exception(f"Error: Object {I} has no faces. Extrusion is not possible. Objects should be flat.")
            
            object_I_planes_verts, object_I_planes_faces, _ = separate_loose_mesh(verts_i, faces_i)

            for IJ in range(len(object_I_planes_verts)):
                object_I_plane_IJ_verts, object_I_plane_IJ_faces = object_I_planes_verts[IJ], object_I_planes_faces[IJ]

                try:
                    bm = bmesh_from_pydata(object_I_plane_IJ_verts, None, object_I_plane_IJ_faces, normal_update=True)
                    bm.edges.ensure_lookup_table()
                    edges = [[e.verts[0].index, e.verts[1].index] for e in bm.edges]
                    object_I_plane_IJ_contours_edges, _, _ = Edges.process(bm, "Boundary", edges)
                    bm.free()
                except Exception as ex:
                    # Keep shape to show as errors in the future
                    contours_failed_at_all.append(object_I_plane_IJ_verts)
                    continue

                if not object_I_plane_IJ_contours_edges:
                    raise Exception(f"Error: Object {I} has no boundaries. Extrusion is not possible. Objects should be flat.")
                # separate contours of every island
                object_I_plane_IJ_contours_verts, edges_boundaries, _ = separate_loose_mesh(object_I_plane_IJ_verts, object_I_plane_IJ_contours_edges)

                object_I_plane_IJ_contours = []
                object_area_boundaries = []
                objects_offsets_of_boundary = []
                failed_contours_vertices = []
                areas = []
                for IJK in range(len(object_I_plane_IJ_contours_verts)):
                    object_I_plane_IJ_contour_IJK_verts, object_I_plane_IJ_contour_IJK_edges = object_I_plane_IJ_contours_verts[len(object_I_plane_IJ_contours_verts)-1-IJK], edges_boundaries[len(object_I_plane_IJ_contours_verts)-1-IJK]
                    object_I_plane_IJ_contour_IJK_verts_sorted = vertices_sort_by_edges(object_I_plane_IJ_contour_IJK_verts, object_I_plane_IJ_contour_IJK_edges)
                    res_boundaries_verts.append(object_I_plane_IJ_contour_IJK_verts_sorted)
                    area = areas_from_polygons(object_I_plane_IJ_contour_IJK_verts_sorted, [list(range(len(object_I_plane_IJ_contour_IJK_verts_sorted)))], )
                    areas.append(area[0])
                    object_I_plane_IJ_contours.append(object_I_plane_IJ_contour_IJK_verts_sorted)
                    object_area_boundaries.append({"area":area, "object_idx":I, "object_boundaries":object_I_plane_IJ_contour_IJK_verts_sorted})
                    pass
                srt = sort_together([areas, object_I_plane_IJ_contours, ])
                object_I_plane_IJ_contours_sorted_by_area = list(reversed(srt[1]))  # First contour is outer boundary - another is holes

                # objects_boundaries.append({"idx": I, "boundaries":object_boundaries_sorted_by_area,})
                # objects_offsets_of_boundaries.append( {"idx":I, "offsets": ss_offsets,} )
                # objects_area_boundaries.append( {"idx":I, "areas":object_area_boundaries,})
                
                if shapes_mode_1 in [ 'EXCLUDE_HOLES', 'INVERT_HOLES_SOFT', 'INVERT_HOLES_HARD',]: # and len(object_boundaries_sorted_by_area)>1:
                    for IJK in range( len(object_I_plane_IJ_contours_sorted_by_area) ):
                        
                        if shapes_mode_1=='INVERT_HOLES_HARD':
                            # Skip add outer boundary any way. If it is single boundary then shape will not compute.
                            if IJK==0:
                                continue

                        if shapes_mode_1=='INVERT_HOLES_SOFT':
                            # if shape_mode is 'INVERT_HOLES_SOFT' and shape has more than one contour then first contour excluded
                            # and all another contour processed as external contours else keep outer boundary
                            if len(object_I_plane_IJ_contours_sorted_by_area)>1:
                                if IJK==0:
                                    # skip outer boundary
                                    continue
                                else:
                                    # keep outer boundary
                                    pass
                            else:
                                # keep outer boundary
                                pass

                        object_I_plane_IJ_contours_sorted_by_area_IJK = object_I_plane_IJ_contours_sorted_by_area[IJK],
                        if I not in objects_data:
                            objects_data[I] = {"idx": I, 'offsets': ss_offsets, 'altitudes': ss_altitudes, 'planes':[]}
                        objects_data[I]['planes'].append(object_I_plane_IJ_contours_sorted_by_area_IJK)
                        
                        if shapes_mode_1=='EXCLUDE_HOLES':
                            # if shape_mode is 'EXCLUDE HOLES' then only first contour need to processed
                            break
                    pass
                elif shapes_mode_1=="FULL_MODE":
                    if I not in objects_data:
                        objects_data[I] = {"idx": I, 'offsets': ss_offsets, 'altitudes': ss_altitudes, 'planes':[]}
                    objects_data[I]['planes'].append(object_I_plane_IJ_contours_sorted_by_area)
                    pass
                else:
                    raise Exception(f"unknown Shapes mode value: '{_shapes_modes[I]}'. Allowed values {allowed_shapes_modes}")
                pass
            pass
        pass

        errors_vertices = []
        if not file_name_dat:
            lst_errors = []
            was_errors = False
            
            def parallel_straight_skeleton_2d_offset(data1):
                new_mesh = pySVCGAL_straight_skeleton_2d_offset(
                    data1['object_id'],
                    data1['polygon_id'],
                    data1['offsets'],
                    data1['altitudes'],
                    data1['planes'],
                    data1['only_tests_for_valid'],
                    data1['res_type'],
                    data1['force_z_zero'],
                    data1['verbose']
                    )
                return new_mesh
            
            #with ThreadPoolExecutor() as executor:
            #data_copy = []
            if(self.res_type=='CONTOURS'):
                res_type=0
            elif(self.res_type=='FACES'):
                res_type=1
            else:
                raise Exception(f"Unknown res_type={self.res_type}. Allowed only 'CONTOURS' or 'FACES'.")

            data = {
                'objects' : [],
                'force_z_zero': self.force_z_zero, 
                'res_type': res_type, 
                'only_tests_for_valid': self.only_tests_for_valid, 
                'verbose' : self.verbose_messages_while_process,
            }
            
            for I in range(len(objects_data)):
                objects_data_I       = objects_data[I]
                offsets_I            = objects_data_I["offsets"]
                altitudes_I          = objects_data_I["altitudes"]
                offsets = []
                altitudes = []
                for offset_index, offset1 in enumerate(offsets_I):
                    if offset_index<=len(ss_altitudes)-1:
                        ss_altitude1 = altitudes_I[offset_index]
                    else:
                        ss_altitude1 = altitudes_I[-1]
                    offsets.append(offset1)
                    altitudes.append(ss_altitude1)
                
                if len(offsets)>0:
                    data['objects'].append( {
                        'object_id':objects_data_I['idx'],
                        'polygon_id':I, 
                        'offsets': offsets,
                        'altitudes': altitudes,
                        'planes' : objects_data_I["planes"], # I is not wrong, boundary1 (array of contours) - plane
                    } )

            # run all skeletons in Threads
            #data_processed = list( executor.map(parallel_straight_skeleton_2d_offset, data))
            data_processed = pySVCGAL_straight_skeleton_2d_offset(data)
            faces_delta = 0
            
            object_verts_merge = []
            object_edges_merge = []
            object_faces_merge = []

            objects_verts_keep = dict()
            objects_edges_keep = dict()
            objects_faces_keep = dict()
            objects_faces_keep_delta = dict()

            lst_errors1 = []

            valid_offsets_merge = []
            valid_altitudes_merge = []

            valid_offsets_keep = dict()
            valid_altitudes_keep = dict()

            polygon_id = 'undefined' # data1['polygon_id']
            if data_processed['has_error']==True:
                was_errors = True
                if 'ftcs_count' in data_processed and data_processed['ftcs_count']>0:
                    lst_errors1.append(f"Polygon : {polygon_id} is failed. ")
                    if data_processed['str_error']:
                        lst_errors1[-1] = lst_errors1[-1] + (data_processed['str_error'])
                    for s in data_processed['ftcs_vertices_description']:
                        if s:
                            lst_errors1.append(f'{s}')
                    failed_contours_vertices.extend(data_processed['ftcs_vertices_list'])
                pass
            
            for data1 in data_processed['objects']:
                object_index = data1["object_index"]
                error_vertices_object1 = []
                if(len(data1['vertices_of_errors'])>0):
                    error_vertices_object1 = data1['vertices_of_errors']
                    if self.verbose_messages_while_process==True:
                        print(f'Object {object_index} has errors:')
                        for s in data1['descriptions_per_errors']:
                            print(f'    {s}')
                errors_vertices.append(error_vertices_object1)
                #else:
                #print(f"\nPolygon_id: {polygon_id} is good. It has no errors")

                # Даже если была ошибка, то проверить, может есть возможность отобразить хоть какие-то данные? Тем более, если ошибки не было!
                if self.only_tests_for_valid==True:
                    # no result, no output
                    pass
                else:
                    # Нельзя пропускать, иначе не будет соответствия исходных объектов и результирующих если по кому-то не получено результатов!!!
                    # if len(data1["vertices"])==0:
                    #     pass
                    # else:
                        if self.join_mode=='SPLIT':
                            # res_offsets.append( [ data1['offset'] ] )
                            # res_altitudes.append( [ data1['altitude'] ] )

                            res_verts.append( data1['vertices'] )
                            res_edges.append( data1['edges']    )
                            res_faces.append( data1['faces']    )
                            pass
                        elif self.join_mode=='KEEP':
                            object_index = data1['object_index']
                            if object_index not in objects_verts_keep:
                                objects_verts_keep[object_index] = []
                                objects_edges_keep[object_index] = []
                                objects_faces_keep[object_index] = []

                                valid_offsets_keep  [object_index] = []
                                valid_altitudes_keep[object_index] = []

                                pass
                            objects_verts_keep[object_index].extend( data1['vertices'] )
                            objects_edges_keep[object_index].extend( data1['edges'] )
                            objects_faces_keep[object_index].extend( data1['faces'] )

                            # valid_offsets_keep  [object_id].append(data1['offset'])
                            # valid_altitudes_keep[object_id].append(data1['altitude'])

                            pass
                        elif self.join_mode=='MERGE':
                            object_verts_merge.extend(data1['vertices'])
                            object_edges_merge.extend( [ list(map(lambda n: n+faces_delta, face)) for face in data1['edges'] ] )
                            object_faces_merge.extend( [ list(map(lambda n: n+faces_delta, face)) for face in data1['faces'] ] )
                            faces_delta+=len(data1['vertices'])

                            # valid_offsets_merge.append(data1['offset'])
                            # valid_altitudes_merge.append(data1['altitude'])

                            pass

                        len_verts1 = len(data1['vertices'])
                        len_edges1 = len(data1['edges'])
                        len_faces1 = len(data1['faces'])
                        #idx = data1['polygon_id']
                        #str_error = f'Polygon {idx} is good. Stright Skeleton mesh: verts {len_verts1}, edges {len_edges1}, faces {len_faces1}'
                        #lst_errors1.append(str_error)
                pass
            lst_errors.extend(lst_errors1)
            if self.join_mode=='MERGE':
                res_verts.append(object_verts_merge)
                res_edges.append(object_edges_merge)
                res_faces.append(object_faces_merge)

                res_offsets.append(valid_offsets_merge)
                res_altitudes.append(valid_altitudes_merge)

                pass

            elif self.join_mode=='KEEP':
                for KEY in objects_verts_keep:
                    res_verts.append(objects_verts_keep[KEY])
                    res_edges.append(objects_edges_keep[KEY])
                    res_faces.append(objects_faces_keep[KEY])

                    res_offsets.append(valid_offsets_keep[KEY])
                    res_altitudes.append(valid_altitudes_keep[KEY])
            else:
                pass
            if len(contours_failed_at_all)>0:
                failed_contours_vertices.extend(contours_failed_at_all)
            pass

            if was_errors:
                print("")
                print("")
                print("Node Skeleton Finished with errors.")
                if self.verbose_messages_while_process==False:
                    print("for more info turn on verbose mode in node")
                else:
                    for s in lst_errors:
                        print(s)

            else:
                if self.verbose_messages_while_process==True:
                    print("\nNode Skeleton Finished.")


        else: # file_name_dat:

            # # for DEVELOPERS:
            # lines_verts = []
            # lines_angles = []
            # # for .dat format save only vertices of first object.
            # # Записывать вершины только первого объекта, т.к. только один объект и может быть рассчитал в CGAL
            # # Когда сделаю компонент, то тогда передам все объекты по очереди.
            # objects_boundaries_0 = objects_boundaries[0]
            # objects_angles_of_boundaries_0 = objects_angles_of_boundaries[0][0]
            # for I in range(len(objects_boundaries_0)):
            #     objects_boundaries_0_I = objects_boundaries_0[I]
            #     lines_verts .append(str(len(objects_boundaries_0_I)),)
            #     if len(objects_boundaries_0_I)>0:
            #         # Если контур только один, внешний, то добавление количества углов приводит к сбою.
            #         # При обном контуре не добавлять количество углов в первую строку
            #         lines_angles.append(str(len(objects_boundaries_0_I)),)
                
            #     for J, vert in enumerate(objects_boundaries_0_I):
            #         v_str = [str(v) for v in vert[:2] ]
            #         v_line = " ".join(v_str)
            #         lines_verts.append(v_line)
            #     for angle in objects_angles_of_boundaries_0:
            #         lines_angles.append( str(self.ss_angle*180/math.pi) )
            # txt_verts  = "\n".join(lines_verts)
            # txt_angles = "\n".join(lines_angles)

            # print(f"stright skeleton node write to file")
            # with open(file_name_dat, "w") as file:
            #     file.write(txt_verts)
            #     print(f'Записаны вершины {len(lines_verts)-1}: {file_name_dat}')
            # with open(file_name_dat+'.angles', "w") as file:
            #     file.write(txt_angles)
            #     print(f'Записаны углы: {len(lines_angles)-1}: {file_name_dat}.angles')
            raise Exception("Mode Save File not realized and used only by developers")

        self.outputs['vertices'].sv_set(res_verts)
        self.outputs['edges'].sv_set(res_edges)
        self.outputs['polygons'].sv_set(res_faces)
        self.outputs['offsets'].sv_set(res_offsets)
        self.outputs['altitudes'].sv_set(res_altitudes)
        self.outputs['failed_contours_vertices'].sv_set(errors_vertices)

        pass
    
    def saveCGALDatFile(self):
        if not all([sock.is_linked for sock in self.inputs if sock.name not in ['ss_angles', 'file_name'] ]):
            return 'Vertices и Faces not connected. Files are not saved.'

        print("file .dat saved")
        pass

classes = [SvSaveCGALDatFile, SvStraightSkeleton2DOffset,]
register, unregister = bpy.utils.register_classes_factory(classes)