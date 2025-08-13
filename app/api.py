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


@app.post("/simulation")
async def run_simulation(input_data: SimulationInput):
    try:
        logging.info(f"Received input data: {input_data.json()}")
        simulator = SupplyChainSimulator(input_data)
        results, profit_loss = simulator.run()
        summary = simulator.compute_summary()
        logging.info(f"Calculated profit_loss: {profit_loss}")
        return {
            "message": "Simulation completed successfully.",
            "results": results,
            "profit_loss": profit_loss,
            "summary": summary,
        }
    except Exception as e:
        import traceback

        logging.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {str(e)}"
        )


@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Error</h1><p>index.html not found.</p>", status_code=404)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

