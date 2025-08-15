import logging
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from domain.models import SimulationInput
from engine.simulator import SupplyChainSimulator


_log_level = os.getenv("SIM_LOG_LEVEL", "INFO").upper()
_log_to_file = os.getenv("SIM_LOG_TO_FILE", "0") == "1"
_handlers = [logging.StreamHandler()]
if _log_to_file:
    _handlers.append(logging.FileHandler("simulation.log"))
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=_handlers,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Cache last summary for GET /summary
_LAST_SUMMARY = None


def validate_input(input_data: SimulationInput) -> None:
    # Node name uniqueness
    names = [n.name for n in input_data.nodes]
    if len(names) != len(set(names)):
        dup = [x for x in names if names.count(x) > 1]
        raise HTTPException(
            status_code=422, detail=f"Duplicate node names: {sorted(set(dup))}"
        )
    name_set = set(names)
    # Network links referential integrity and duplicate detection
    seen = set()
    for l in input_data.network:
        if l.from_node not in name_set or l.to_node not in name_set:
            raise HTTPException(
                status_code=422,
                detail=f"Network link refers unknown node: {l.from_node}->{l.to_node}",
            )
        key = (l.from_node, l.to_node)
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate network link: {l.from_node}->{l.to_node}",
            )
        seen.add(key)


@app.post("/simulation")
async def run_simulation(input_data: SimulationInput):
    try:
        validate_input(input_data)
        logging.info(f"Received input data: {input_data.json()}")
        simulator = SupplyChainSimulator(input_data)
        results, profit_loss = simulator.run()
        summary = simulator.compute_summary()
        logging.info(f"Calculated profit_loss: {profit_loss}")
        global _LAST_SUMMARY
        _LAST_SUMMARY = summary
        return {
            "message": "Simulation completed successfully.",
            "results": results,
            "profit_loss": profit_loss,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error during simulation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Error</h1><p>index.html not found.</p>", status_code=404
        )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/summary")
async def get_summary():
    if _LAST_SUMMARY is None:
        raise HTTPException(
            status_code=404, detail="No summary available yet. Run a simulation first."
        )
    return _LAST_SUMMARY
