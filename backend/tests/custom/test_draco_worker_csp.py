"""O worker Draco da prévia 3D recebe o CSP de worker do upstream (só 'wasm-unsafe-eval'); o documento não muda."""

from backend.app.custom.draco_worker_csp import WORKER_PATH, allow_draco_worker


async def test_draco_worker_gets_wasm_csp(async_client):
    allow_draco_worker()
    allow_draco_worker()  # idempotente
    worker = await async_client.get(WORKER_PATH)
    page = await async_client.get("/")
    assert "'wasm-unsafe-eval'" in worker.headers["content-security-policy"]
    assert "unsafe-eval'" not in worker.headers["content-security-policy"].replace("'wasm-unsafe-eval'", "")
    assert "wasm-unsafe-eval" not in page.headers.get("content-security-policy", "")
