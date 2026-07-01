# -*- coding: utf-8 -*-
# Ghidra headless script - metadata + decompiled export v2 (optimized)

import json
import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

OUTPUT_DIR = "/tmp/decompiled_v2"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

program = getCurrentProgram()
name = program.getName()
fm = program.getFunctionManager()
mem = program.getMemory()
listing = program.getListing()
refManager = program.getReferenceManager()
monitor = ConsoleTaskMonitor()

def is_string_type(dt_name):
    dt_lower = dt_name.lower()
    return ('string' in dt_lower or 'char' in dt_lower or
            'unicode' in dt_lower or 'utf' in dt_lower)

# ============================================================
# 1. STRING TABLE
# ============================================================
print("Phase 1: Collecting strings...")
string_list = []
data_iter = listing.getDefinedData(True)
while data_iter.hasNext():
    du = data_iter.next()
    dt_name = str(du.getDataType())
    if is_string_type(dt_name):
        try:
            val = str(du.getDefaultValueRepresentation())
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
        except:
            val = ""
        string_list.append({
            "address": str(du.getAddress()),
            "value": val,
            "length": du.getLength()
        })
print("  Found %d strings" % len(string_list))

# ============================================================
# 2. STRING XREFS
# ============================================================
print("Phase 2: Collecting string xrefs...")
string_xrefs = []
for entry in string_list:
    str_addr = toAddr(entry["address"])
    refs = refManager.getReferencesTo(str_addr)
    for ref in refs:
        from_addr = ref.getFromAddress()
        func = fm.getFunctionContaining(from_addr)
        string_xrefs.append({
            "string_addr": entry["address"],
            "string_value": entry["value"],
            "ref_addr": str(from_addr),
            "ref_type": str(ref.getReferenceType()),
            "containing_function": func.getName() if func else "NONE",
            "function_addr": str(func.getEntryPoint()) if func else "NONE"
        })
print("  Found %d string xrefs" % len(string_xrefs))

# ============================================================
# 3. FUNCTION LIST + CALL GRAPH
# ============================================================
print("Phase 3: Collecting functions and call graph...")
func_list = []
func_addr_set = set()
for func in fm.getFunctions(True):
    ea = str(func.getEntryPoint())
    func_addr_set.add(ea)
    func_list.append({"address": ea, "name": func.getName(),
                      "size": func.getBody().getNumAddresses(),
                      "calling": [], "called_by": []})

func_addr_to_idx = {f["address"]: i for i, f in enumerate(func_list)}

for func in fm.getFunctions(True):
    fe = str(func.getEntryPoint())
    if fe not in func_addr_to_idx:
        continue
    idx = func_addr_to_idx[fe]
    called = set()
    for ref in refManager.getReferencesFrom(func.getEntryPoint()):
        if ref.getReferenceType().isCall():
            t = str(ref.getToAddress())
            if t in func_addr_set:
                called.add(t)
    func_list[idx]["calling"] = sorted(called)

for f in func_list:
    for c in f["calling"]:
        if c in func_addr_to_idx:
            func_list[func_addr_to_idx[c]]["called_by"].append(f["address"])
for f in func_list:
    f["calling_count"] = len(f["calling"])
    f["called_by_count"] = len(f["called_by"])
print("  Found %d functions" % len(func_list))

# ============================================================
# 4. DECOMPILE ALL FUNCTIONS
# ============================================================
print("Phase 4: Decompiling all functions...")
decomp = DecompInterface()
decomp.openProgram(program)
decomp.setSimplificationStyle("decompile")
decompile_errors = []
count = 0
for f in func_list:
    addr = toAddr(f["address"])
    func = fm.getFunctionAt(addr)
    if not func:
        f["decompiled"] = ""
        continue
    result = decomp.decompileFunction(func, 30, monitor)
    c_code = ""
    if result and result.decompileCompleted():
        hf = result.getHighFunction()
        if hf:
            c_code = result.getDecompiledFunction().getC()
    else:
        decompile_errors.append({"address": f["address"], "name": f["name"]})
    f["decompiled"] = c_code
    count += 1
    if count % 200 == 0:
        print("  Decompilation: %d / %d" % (count, len(func_list)))
decomp.dispose()
print("  Decompiled %d functions (%d errors)" % (count, len(decompile_errors)))

# ============================================================
# 5. MEMORY BLOCKS
# ============================================================
print("Phase 5: Collecting memory blocks...")
memory_blocks = []
for block in mem.getBlocks():
    memory_blocks.append({
        "name": block.getName(),
        "start": str(block.getStart()),
        "end": str(block.getEnd()),
        "size": block.getSize(),
        "execute": block.isExecute()
    })

# ============================================================
# 6. SAVE OUTPUTS
# ============================================================
print("Phase 6: Saving outputs...")

full_data = {
    "program": name,
    "strings": string_list,
    "string_xrefs": string_xrefs,
    "functions": func_list,
    "memory_blocks": memory_blocks,
    "decompile_errors": decompile_errors
}

json_path = os.path.join(OUTPUT_DIR, name + "_full.json")
with open(json_path, "w") as f:
    json.dump(full_data, f, indent=2)

c_path = os.path.join(OUTPUT_DIR, name + "_decompiled.c")
with open(c_path, "w") as f:
    for entry in func_list:
        f.write("// %s @ %s (%d bytes, called_by=%d, calls=%d)\n" % (
            entry["name"], entry["address"], entry["size"],
            entry["called_by_count"], entry["calling_count"]))
        f.write(entry["decompiled"])
        f.write("\n\n")

# Separate files for quick access
with open(os.path.join(OUTPUT_DIR, name + "_strings.json"), "w") as f:
    json.dump(string_list, f, indent=2)
with open(os.path.join(OUTPUT_DIR, name + "_string_xrefs.json"), "w") as f:
    json.dump(string_xrefs, f, indent=2)
with open(os.path.join(OUTPUT_DIR, name + "_callgraph.json"), "w") as f:
    json.dump([{"address": x["address"], "name": x["name"],
                "calling": x["calling"], "called_by": x["called_by"]}
               for x in func_list], f, indent=2)

print("  JSON: %s" % json_path)
print("  C: %s" % c_path)
print("  Strings: %d" % len(string_list))
print("  String xrefs: %d" % len(string_xrefs))
print("  Functions: %d" % len(func_list))
print("\nDone!")
