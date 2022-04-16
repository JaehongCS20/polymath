from polymath.srdfg.passes import register_pass, Pass
from polymath.srdfg.templates import fused_dnn
import polymath as pm
import inspect
from collections import defaultdict, namedtuple

NON_DNN_NODE_OPS = (pm.write, pm.placeholder, pm.index, pm.var_index,
                    pm.slice_op, pm.func_op, pm.GroupNode, pm.NonLinear)
BATCH_FUNCS = {}

FusionDescription = namedtuple('FusionDescription', ['output', 'layer'])

FUSION_NAME_MAPPING = {
    'conv': 'conv_bias',
    'relu': 'relu',
    'leakyrelu': 'leaky_relu',
    'add': 'elem_add',
    'sub': 'elem_sub',
    'reducemean': 'reduce_mean',
    'mul': 'elem_mul',
    'div': 'elem_div',
    'sqrt': 'elem_sqrt',
    'depthwiseconv': 'depthwise_conv_bias',
    'maxpool': 'max_pool',
    'globalaveragepool': 'global_avg_pool',
    'clip': 'elem_clip',
    'averagepool': 'avg_pool',
    'reciprocal': 'reciprocal',
    'matmul': 'matmul',
    'gemm': 'gemm',
    'softmax': 'softmax',
    'transpose': 'tensor_transpose',
    'pow' : 'elem_pow',
    'reshape': 'tensor_reshape',
    'tanh': 'elem_tanh',
    "gelu": "gelu"
}

@register_pass
class FuseOps(Pass):
    def __init__(self, fusion_seqs, pad_conv_constraint=False, test_run=False):
        self.test_run = test_run
        fusion_ops = []
        for o in fusion_seqs:
            seq = []
            for s in o:
                if isinstance(s, list):
                    subseq = []
                    for sub in s:
                        sl = sub.lower()
                        if sl in FUSION_NAME_MAPPING:
                            subseq.append(FUSION_NAME_MAPPING[sl])
                        else:
                            subseq.append(sl)
                    seq.append(subseq)
                else:
                    sl = s.lower()
                    if sl in FUSION_NAME_MAPPING:
                        seq.append(FUSION_NAME_MAPPING[sl])
                    else:
                        seq.append(sl)
            fusion_ops.append(seq)
        assert isinstance(fusion_ops, list) and len(fusion_ops) > 0
        self.pad_conv_constraint = pad_conv_constraint
        self.check_valid_fusions(fusion_ops)
        self.fusion_sequences = fusion_ops
        self.fusion_sequences = sorted(self.fusion_sequences, key=lambda x: len(x), reverse=True)
        self.fusion_starts = [f[0] for f in fusion_ops]
        self.all_fused_nodes = {'layers': [],
                           'fusion_inputs': [],
                           'fusion_outputs': [],
                           'intermediate': []
                           }
        self.fusion_instances = defaultdict(int)
        super(FuseOps, self).__init__()

    def check_valid_fusions(self, fusion_ops):
        missing_ops = []
        for f in fusion_ops:
            name = self.get_fusion_name(f)
            if name not in dir(fused_dnn):
                missing_ops.append((name, f))
        if len(missing_ops) > 0:
            raise RuntimeError(f"Fusion templates do not exist for sequences:"
                               f"\n{missing_ops}")


    def is_conv_dw_conv(self, seq) -> bool:
        return "conv_bias" == seq[0] and "depthwise_conv_bias" in seq

    def is_valid_conv_dw_conv(self, conv_node) -> bool:
        assert conv_node.op_name == "conv_bias"
        return conv_node.inputs[1].shape[2:] == (1, 1)

    def get_possible_fusions(self, n):
        # TODO: Might need to validate the first operation is not a list
        possible_fusions = []
        if self.pad_conv_constraint:
            for s in self.fusion_sequences:
                if s[0] == n.op_name:
                    if not self.is_conv_dw_conv(s):
                        possible_fusions.append(s)
                    elif self.is_valid_conv_dw_conv(n):
                        possible_fusions.append(s)
        else:
            for s in self.fusion_sequences:
                if s[0] == n.op_name:
                    possible_fusions.append(s)
        return possible_fusions

    def initialize_pass(self, graph, ctx):
        nidx = 0
        node_list = list(graph.nodes.values())
        while nidx < len(node_list):
            n = node_list[nidx]

            if not isinstance(n, pm.Template):
                nidx += 1
                continue
            elif n in self.all_fused_nodes['layers']:
                nidx += 1
                continue
            elif any([o in self.all_fused_nodes['fusion_inputs'] for o in n.outputs]):
                    nidx += 1
                    continue

            if n.op_name in self.fusion_starts:
                possible_fusions = self.get_possible_fusions(n)
                for pf in possible_fusions:
                    fused_nodes = self.get_fused_nodes(graph, pf, n)
                    if fused_nodes is not None:
                        self.fuse_layers(graph, fused_nodes, pf)
                        break

            nidx += 1

        return graph

    def cleanup_writes(self, graph, layers, intermediate_nodes, result):
        layer_nodes = []
        for layer_list in layers:
            for l in layer_list:
                assert l.layer.name in graph.nodes
                layer_nodes.append(l.layer)
                graph.nodes.pop(l.layer.name)

        for i in intermediate_nodes:
            if i.op_name == "output":
                i.reset_writes()
            is_read = False
            for n in graph.nodes.values():
                if isinstance(n, pm.Template) and n not in layer_nodes and i in n.inputs:
                    is_read = True
                    break
            if not is_read:
                graph.nodes.pop(i.name)

        assert result.op_name == "output"
        result.reset_writes()

    def flatten_seq(self, list_of_lists):
        if len(list_of_lists) == 0:
            return list_of_lists
        if isinstance(list_of_lists[0], list):
            return self.flatten_seq(list_of_lists[0]) + self.flatten_seq(list_of_lists[1:])
        return list_of_lists[:1] + self.flatten_seq(list_of_lists[1:])

    def get_fusion_name(self, fusion_ops):
        fusion_ops = self.flatten_seq(fusion_ops)
        fusion_name = "_".join(fusion_ops)
        fusion_name = fusion_name.replace("elem_", "").replace("reduce_", "").replace('tensor_', '')
        return fusion_name


    def fuse_layers(self, graph, layers, fusion_ops):
        fusion_name = self.get_fusion_name(fusion_ops)
        instance_name = f"{fusion_name}{self.fusion_instances[fusion_name]}"
        self.fusion_instances[fusion_name] += 1
        if self.test_run:
            return
        intermediate_nodes = []
        for layer_list in layers[:-1]:
            for l in layer_list:
                intermediate_nodes.append(l.output)

        fused_templates = []
        for layer_list in layers:
            for l in layer_list:
                fused_templates.append(l.layer)

        layer_inputs = []
        layer_kwargs = {}
        assert layers[0][0].layer.name in graph.nodes
        argname_counts = defaultdict(int)
        for layer_list in layers:
            for l in layer_list:
                for i in l.layer.inputs:
                    if i not in intermediate_nodes and i not in layer_inputs:
                        layer_inputs.append(i)

                for k, v in l.layer.kwargs.items():
                    if k in layer_kwargs:
                        layer_kwargs[f"{k}{argname_counts[k]}"] = v
                        argname_counts[k] += 1
                    else:
                        layer_kwargs[k] = v


        result = layers[-1][-1].output
        self.cleanup_writes(graph, layers, intermediate_nodes, result)
        layer_inputs.append(result)

        self.all_fused_nodes['intermediate'] += intermediate_nodes
        self.all_fused_nodes['layers'] += fused_templates
        self.all_fused_nodes['fusion_inputs'] += layer_inputs
        self.all_fused_nodes['fusion_outputs'].append(result)



        signature = inspect.signature(getattr(fused_dnn, fusion_name).define_graph)

        all_arg_len = len(signature.parameters.keys()) - 1
        args = []
        kwargs = []
        for k, v in signature.parameters.items():
            if v.default is v.empty:
                args.append(k)
            else:
                kwargs.append(k)
        if len(args) - 1 != len(layer_inputs) or len(kwargs) != len(layer_kwargs):
        # if all_arg_len != len(layer_inputs) + len(layer_kwargs):

            raise RuntimeError(f"Invalid arguments for layer fusion in {fusion_name}:\n"
                               f"Fusion signature args: {args}\n"
                               f"Fusion signature kwargs: {kwargs}\n"
                               f"Layer args: {[n.name for n in layer_inputs]}\n"
                               f"Kwargs: {layer_kwargs.keys()}")
        with graph:
            node = getattr(fused_dnn, fusion_name)(*layer_inputs, name=instance_name, **layer_kwargs)

        self.topological_insert(graph, node)

    def topological_insert(self, graph, node):
        assert isinstance(node, pm.Node) and hasattr(node, 'inputs')
        assert all([i.name in graph.nodes for i in node.inputs])
        graph.nodes.pop(node.name)
        min_idx = 0

        for k, n in graph.nodes.items():
            i = list(graph.nodes.keys()).index(k)
            if isinstance(n, pm.Template):
                for o in n.outputs:
                    if o in node.inputs and i > min_idx:
                        min_idx = i
            elif n in node.inputs and i > min_idx:
                min_idx = i

        out = graph.nodes.pop(node.outputs[0].name)
        graph.insert_node(out, min_idx + 1)
        graph.insert_node(node, min_idx + 1)



    def get_fused_nodes(self, graph, sequence, initial_layer):
        # TODO: Make sure the output isnt used in multiple places
        assert hasattr(initial_layer, "outputs") and len(initial_layer.outputs) == 1
        tgt_input = initial_layer.outputs[0]
        fdescriptors = [
            [FusionDescription(output=tgt_input, layer=initial_layer)]]
        for i, l in enumerate(sequence[1:]):
            fl = self.get_fusable_layer(graph, l, tgt_input)
            if fl is None:
                return None
            else:
                assert isinstance(fl, list)
                tgt_input = fl[0].output
                fdescriptors.append(fl)
        return fdescriptors

    def get_fusable_layer(self, graph, layer_name, input_node):
        if isinstance(layer_name, list):
            out_layers = []
            outputs = []
            for l in layer_name:
                for name, n in graph.nodes.items():
                    if isinstance(n, pm.Template) and n.op_name == l and input_node in n.inputs and n.outputs[0] not in outputs:
                        assert hasattr(n, "outputs") and len(n.outputs) == 1
                        out_layers.append(FusionDescription(output=n.outputs[0], layer=n))
                        outputs.append(n.outputs[0])
            if len(out_layers) == len(layer_name):
                return out_layers

        else:
            for name, n in graph.nodes.items():
                if isinstance(n, pm.Template) and n.op_name == layer_name and input_node in n.inputs:
                    assert hasattr(n, "outputs") and len(n.outputs) == 1
                    return [FusionDescription(output=n.outputs[0], layer=n)]
        return None

    def num_fusions(self):
        return self.fusion_instances

@register_pass
class CollectDNNShapes(Pass):
    def __init__(self):
        self.op_counter = defaultdict(int)
        self.shape_tracker = {}
        super(CollectDNNShapes, self).__init__()

    def apply_pass(self, node, ctx):
        if node.op_name in pm.ONNX_OP_NAMES:
            shapes = []
            for i in node.inputs:
                if isinstance(i, pm.Node):
                    shapes.append(i.shape)
            for o in node.outputs:
                if isinstance(o, pm.Node):
                    shapes.append(o.shape)
            self.shape_tracker[f"{node.op_name}{self.op_counter[node.op_name]}"] = shapes
            self.op_counter[node.op_name] += 1

@register_pass
class UpdateBatchSize(Pass):
    def __init__(self, batch_size, graph_name):
        self.graph_name = graph_name
        self.batch_size = batch_size
        self.op_counter = defaultdict(int)
        self.shape_tracker = {}
        super(UpdateBatchSize, self).__init__()

    def apply_pass(self, node, ctx):
        if not isinstance(node, NON_DNN_NODE_OPS) and node.op_name != self.graph_name and node.name != self.graph_name:
            assert node.op_name in BATCH_FUNCS, f"{node.op_name}, {self.graph_name}, {node.name}"
            node, shape_list = BATCH_FUNCS[node.op_name](node, self.batch_size)
            self.shape_tracker[f"{node.op_name}{self.op_counter[node.op_name]}"] = shape_list
            self.op_counter[node.op_name] += 1
        return node

@register_pass
class RenameMultiDimOps(Pass):
    MULTI_DIM_OP_DEFAULTS = {
        'sgd': -1, 'elem_tanh': -1, 'elem_tanh_grad': -1, 'relu': 4, 'relu_grad': 4, "elem_ceil": -1, "elem_pow": -1,
        "reduce_mean": -1, "reduce_min": -1, "tensor_transpose": -1, "matmul": 2, 'softmax': 2, 'add_add': 3, "elem_add": 4
    }
    MULTI_OPERAND_OPS = ['tensor_reshape']
    def __init__(self):
        super(RenameMultiDimOps, self).__init__()

    def apply_pass(self, node, ctx):
        if node.op_name in RenameMultiDimOps.MULTI_DIM_OP_DEFAULTS.keys():
            node = self.rename_op(node)
        elif node.op_name in RenameMultiDimOps.MULTI_OPERAND_OPS:
            node = self.rename_multi_operand_op(node)
        return node

    def rename_multi_operand_op(self, node):
        assert len(node.inputs) == 1 and len(node.outputs) == 1
        node.op_name = f"{node.op_name}{str(len(node.inputs[0].shape))}d{str(len(node.outputs[0].shape))}d"

    def rename_op(self, node):

        default_size = RenameMultiDimOps.MULTI_DIM_OP_DEFAULTS[node.op_name]
        if len(node.inputs[0].shape) != default_size:
            node.op_name = f"{node.op_name}{str(len(node.inputs[0].shape))}d"

        return node

@register_pass
class UpdateLayout(Pass):
    UNIQUE_OPS = ['conv', 'conv_bias', 'global_average_pool_grad', 'max_pool_grad', 'avg_pool', 'average_pool_grad']
    def __init__(self, current_layout, new_layout):

        assert current_layout == 'nchw'
        assert new_layout == 'nhwc'
        self.layout_map = {}
        self.layout_map[0] = 0
        self.layout_map[1] = 3
        self.layout_map[2] = 2
        self.layout_map[3] = 1
        self.updated_shapes = {}

        super(UpdateLayout, self).__init__()

    def apply_pass(self, node, ctx):
        if isinstance(node, (pm.write, pm.placeholder, pm.temp)) and len(node.shape) == 4:
            node = self.update_shape(node)
        elif node.op_name in UpdateLayout.UNIQUE_OPS:
            node = self.handle_unique_op(node)
        return node


    def update_shape(self, node):
        new_shape = tuple([node.shape[self.layout_map[i]] for i in range(len(node.shape))])
        if node.name in self.updated_shapes:
            assert self.updated_shapes[node.name] == new_shape, f"Invalid shapes for {node.name}:\n" \
                                                                f"Previous shape: {self.updated_shapes[node.name]}\n" \
                                                                f"New shape: {node.shape}"

        self.updated_shapes[node.name] = new_shape
        node.shape = new_shape
        return node

    def handle_unique_op(self, node):
        if node.op_name in ['conv', 'conv_bias']:
            weight = node.inputs[1]
            if weight.name in self.updated_shapes:
                original_shape = self.get_original_shape(self.updated_shapes[weight.name])
            else:
                original_shape = weight.shape
            weight.shape = (original_shape[2], original_shape[3], original_shape[0], original_shape[1])

            activation = node.inputs[0]
            if activation.name not in self.updated_shapes:
                activation = self.update_shape(activation)
            output = node.outputs[0]

            if output.name not in self.updated_shapes:
                output = self.update_shape(output)

        elif node.op_name in ['global_average_pool_grad', 'max_pool_grad', 'average_pool_grad']:
            for i in node.inputs:
                if isinstance(i, pm.Node) and len(i.shape) == 4:
                    if i.name not in self.updated_shapes:
                        i = self.update_shape(i)

            for i in node.outputs:
                if isinstance(i, pm.Node) and len(i.shape) == 4:
                    if i.name not in self.updated_shapes:
                        i = self.update_shape(i)

        return node

    def get_original_shape(self, new_shape):
        rev_map = {v: k for k, v in self.layout_map.items()}
        orig_shape = tuple([new_shape[rev_map[i]] for i in range(len(new_shape))])
        return orig_shape


def conv_bias_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [act.shape, out.shape]

def conv_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [act.shape, out.shape]

def relu_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [act.shape, out.shape]

def elem_tanh_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape[0] = batch_size
    out.shape[0] = batch_size
    return node, [act.shape, out.shape]

def batch_norm_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [act.shape, out.shape]

def flatten_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1]])
    return node, [act.shape, out.shape]

def elem_add_batch(node, batch_size):
    op1 = node.inputs[0]
    op2 = node.inputs[1]
    out = node.outputs[0]
    op1.shape = tuple([batch_size, op1.shape[1], op1.shape[2], op1.shape[3]])
    op2.shape = tuple([batch_size, op2.shape[1], op2.shape[2], op2.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [op1.shape, op2.shape, out.shape]

def global_avg_pool_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [act.shape, out.shape]

def max_pool_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [act.shape, out.shape]

def avg_pool_batch(node, batch_size):
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    out.shape = tuple([batch_size, out.shape[1], out.shape[2], out.shape[3]])
    return node, [act.shape, out.shape]

def gemm_batch(node, batch_size):
    # TODO: Check for transpose in kwargs
    act = node.inputs[0]
    out = node.outputs[0]
    act.shape = tuple([batch_size, act.shape[1]])
    out.shape = tuple([batch_size, out.shape[1]])
    return node, [act.shape, out.shape]

def mean_var_batch(node, batch_size):
    act = node.inputs[0]
    act.shape = tuple([batch_size, act.shape[1], act.shape[2], act.shape[3]])
    return node, [act.shape]


BATCH_FUNCS['conv_bias'] = conv_bias_batch
BATCH_FUNCS['conv'] = conv_batch
BATCH_FUNCS['relu'] = relu_batch
BATCH_FUNCS['elem_tanh'] = elem_tanh_batch
BATCH_FUNCS['coarse_flatten'] = flatten_batch
BATCH_FUNCS['elem_add'] = elem_add_batch
BATCH_FUNCS['global_avg_pool'] = global_avg_pool_batch
BATCH_FUNCS['max_pool'] = max_pool_batch
BATCH_FUNCS['avg_pool'] = avg_pool_batch
BATCH_FUNCS['batch_norm'] = batch_norm_batch
BATCH_FUNCS['gemm'] = gemm_batch
BATCH_FUNCS['mean_var'] = mean_var_batch

