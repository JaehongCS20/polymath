import polymath as pm
from tests.util import linear, op_counts, logistic, svm, reco, dense, conv, two_layer_dense, lenet, tvm_lenet
from pathlib import Path
import islpy as isl
import tvm
import pytest
import pprint
import numpy as np
import copy
import onnxruntime as rt
from onnx import numpy_helper, helper, defs


def test_lenet():
    # len_graph = lenet()
    inp_info, graph, out_info = lenet()
    tvm_code = pm.generate_tvm(graph, inp_info, "")
    pm_mod = tvm.IRModule.from_expr(tvm_code)
    pm_mod = tvm.relay.transform.InferType()(pm_mod)


    net = tvm_lenet()
    mod = tvm.IRModule.from_expr(net)
    mod = tvm.relay.transform.InferType()(mod)
