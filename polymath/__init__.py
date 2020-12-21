from __future__ import print_function, division, absolute_import

DEFAULT_SHAPES = [(1,), (1,)]
UNSET_SHAPE = tuple([])
SCALAR_IDX = (0,)
# TODO: Need to add all func operators here from base class
from polymath.srdfg.domain import Domain
from polymath.srdfg.base import Node, nodeop, func_op, contains,\
    import_, control_dependencies, pow_, EvaluationError, Graph, int_, \
    mul, sub, add, call, var_index
from polymath.srdfg.nodes import variable, predicate, assert_, str_format, identity, lazy_constant, try_,\
    placeholder, temp, parameter, slice_op, input, state, output, write
from polymath.srdfg.index import index, index_op
from polymath.srdfg.group_nodes import GroupNode, sum, prod, max, min, argmin, argmax, bitreverse
from polymath.srdfg.nonlinear import NonLinear, sigmoid, log2, exp, abs, sqrt, ceil, floor, cast, tanh
from polymath.srdfg.template import Template
from polymath.srdfg.transformations import Transformation, unsqueeze, squeeze, flatten, gather
from polymath.srdfg.util import Profiler, visualize, lower_graph, is_iterable
from polymath.srdfg.serialization.serialize import pb_store, pb_load

from polymath.srdfg.templates.data_analytics import linear_regressor_train,\
    svm_classifier_train, logistic_regressor_train, logistic_regressor

from polymath.srdfg.templates.dnn import conv_bias, dense, relu, avg_pool2d,\
    batch_flatten, softmax, relu1d, dense_sigmoid, batch_norm,\
    global_avg_pool, conv, max_pool, dropout, leaky_relu, avg_pool, lrn, elem_tanh, elem_sigmoid, elem_cast


from polymath.srdfg.templates.math import elem_mul, elem_sub, reduce_sum, matmul, gemm, elem_add, elem_greater, \
    lvmatmul, rvmatmul
from polymath.srdfg.templates.tensor_transformations import coarse_flatten, elem_gather, transpose, onnx_reshape, \
    onnx_squeeze, onnx_identity, onnx_resize, onnx_unsqueeze

from polymath.srdfg.from_onnx.converter import from_onnx, get_attributes, get_value_info_shape

from polymath.srdfg.passes import register_pass, Pass
from polymath.srdfg.passes.compiler_passes import NormalizeGraph, Lower, CountNodes, CountOpTypes
from polymath.codegen.tabla.tabla_translate import generate_tabla

try:
    from polymath.codegen.dnnweavergen.dnnweaver_translate import generate_dnnweaver
except ImportError:
    print(f"WARNING: DNNWeaver translation could not be imported because DNNWeaver is not currently installed.")
    generate_dnnweaver = None

try:
    from polymath.codegen.tvmgen.tvm_translate import generate_tvm
except ImportError:
    print(f"WARNING: TVM translation could not be imported because TVM is not currently installed.")
    generate_tvm = None