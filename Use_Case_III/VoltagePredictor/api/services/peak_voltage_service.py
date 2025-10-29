import pandas as pd
import joblib
from pathlib import Path
from models.models import PeakVoltageListResponse, PeakVoltageRequest, PeakVoltageListRequest, PeakVoltageResponse

class PeakVoltageService:
    """
    Service class for handling peak voltage data
    """
    def __init__(self):
        self.root_path = Path(__file__).parent.parent / 'ml_models'
        self.pipeline = None
        self.scaler = None


    def _load_pipeline(self):
        if self.pipeline is not None:
            return self.pipeline

        pipeline_path = self.root_path / 'pipeline.pkl'
        if not pipeline_path.exists():
            raise FileNotFoundError(f"Pipeline file not found at {pipeline_path}. Please ensure the pipeline is trained and saved.")
        print("📦 Loading pipeline...", flush=True)
        self.pipeline = joblib.load(pipeline_path, mmap_mode="r")
        print("✅ Pipeline loaded", flush=True)
        return self.pipeline


    def _load_scaler(self):
        if self.scaler is not None:
            return self.scaler

        scaler_path = self.root_path / 'scaler_y.pkl'
        if not scaler_path.exists():
            raise FileNotFoundError(f"Scaler file not found at {scaler_path}. Please ensure the scaler is trained and saved.")
        print("📦 Loading scaler...", flush=True)
        self.scaler = joblib.load(scaler_path, mmap_mode="r")
        print("✅ Scaler loaded", flush=True)
        return self.scaler


    def get_peak_voltages(self, request):
        """
        Get peak voltages data
        """
        # Validate and parse the request
        if not isinstance(request, PeakVoltageListRequest):
            raise ValueError("Invalid request format. Expected PeakVoltageListRequest.")

        pipeline = self._load_pipeline()

        # Convert the request data to the format expected by the pipeline
        # The pipeline expects a list of dictionaries, where each dictionary corresponds to a PeakVoltageRequest
        peak_voltage_data = pd.DataFrame([data.model_dump() for data in request.data])
        peak_voltage_data = pipeline.predict(peak_voltage_data)

        # If the user wants scaled data do nothing, else convert the predicted data back to the original scale
        if not request.return_scaled:
            scaler = self._load_scaler()
            peak_voltage_data = scaler.inverse_transform(peak_voltage_data.reshape(-1, 1))

        return PeakVoltageListResponse(
            data=[
                PeakVoltageResponse(**data.model_dump(), U_max=prediction)
                for data, prediction in zip(request.data, peak_voltage_data)
            ]
        )