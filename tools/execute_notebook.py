"""Выполняет все ячейки в свежем ядре и сохраняет отчёт."""
from pathlib import Path
import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

import nbformat
from nbclient import NotebookClient
from jupyter_client import AsyncKernelManager

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

LOCAL_DIRS = {
    'TMP': 'tmp', 'TEMP': 'tmp', 'IPYTHONDIR': 'tmp/ipython',
    'MPLCONFIGDIR': 'tmp/matplotlib', 'PYTHONPYCACHEPREFIX': 'tmp/pycache',
    'JUPYTER_CONFIG_DIR': 'tmp/jupyter/config',
    'JUPYTER_DATA_DIR': 'tmp/jupyter/data',
    'JUPYTER_RUNTIME_DIR': 'tmp/jupyter/runtime',
}
for variable, relative in LOCAL_DIRS.items():
    path = ROOT / relative
    path.mkdir(parents=True, exist_ok=True)
    os.environ[variable] = str(path)
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')

# Ядро использует тот же Python; настройки сохраняются внутри проекта.
kernel_name = 'cosmetics-project'
kernelspec = ROOT / 'tmp/jupyter/data/kernels' / kernel_name
kernelspec.mkdir(parents=True, exist_ok=True)
(kernelspec / 'kernel.json').write_text(json.dumps({
    'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
    'display_name': 'Cosmetics Python',
    'language': 'python',
}), encoding='utf-8')

# Пять каналов Jupyter используют фиксированные локальные порты.
class FixedPortsKernelManager(AsyncKernelManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        (self.shell_port, self.iopub_port, self.stdin_port,
         self.control_port, self.hb_port) = (41870, 41871, 41872, 41873, 41874)

notebook_path = ROOT / 'cosmetics-product-analytics.ipynb'
report_path = ROOT / 'outputs/execution_report.json'
report_path.parent.mkdir(parents=True, exist_ok=True)
notebook = nbformat.read(notebook_path, as_version=4)
nbformat.validate(notebook)
source_hash = hashlib.sha256(json.dumps(
    [(cell.cell_type, cell.source) for cell in notebook.cells], ensure_ascii=False
).encode('utf-8')).hexdigest()
started = time.time()
report = {
    'status': 'running', 'fresh_kernel': True, 'fresh_process': True,
    'execution_mode': 'all notebook cells in a new local Jupyter kernel',
    'kernel_name': kernel_name, 'python_executable': sys.executable,
    'started_utc': datetime.now(timezone.utc).isoformat(),
    'notebook_sources_sha256': source_hash,
    'input_manifest_sha256': hashlib.sha256((ROOT / 'data/source_manifest.json').read_bytes()).hexdigest(),
    'scenario_inputs_sha256': hashlib.sha256((ROOT / 'data/scenario_inputs.csv').read_bytes()).hexdigest(),
    'analytical_cache_present_before_run': (ROOT / 'data/cache/analytics.duckdb').exists(),
}
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

try:
    client = NotebookClient(
        notebook, timeout=None, startup_timeout=90, kernel_name=kernel_name,
        allow_errors=False, resources={'metadata': {'path': str(ROOT)}},
    )
    client.kernel_manager_class = FixedPortsKernelManager
    client.execute()
    nbformat.validate(notebook)
    nbformat.write(notebook, notebook_path)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == 'code']
    report.update({
        'status': 'success', 'code_cells': len(code_cells),
        'executed_cells': sum(cell.execution_count is not None for cell in code_cells),
        'errors': sum(output.output_type == 'error' for cell in code_cells for output in cell.outputs),
        'seconds': time.time() - started,
        'finished_utc': datetime.now(timezone.utc).isoformat(),
        'notebook_file_sha256': hashlib.sha256(notebook_path.read_bytes()).hexdigest(),
    })
except Exception as error:
    report.update({
        'status': 'failed', 'error': type(error).__name__, 'detail': str(error),
        'traceback': traceback.format_exc(), 'seconds': time.time() - started,
        'finished_utc': datetime.now(timezone.utc).isoformat(),
    })
    nbformat.write(notebook, notebook_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    raise

report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
