import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Download, TrendingUp, Bolt, Clock } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

interface ResultsDisplayProps {
  result: any;
  onExportJson: () => void;
  onExportCsv: () => void;
}

export default function ResultsDisplay({ result, onExportJson, onExportCsv }: ResultsDisplayProps) {
  const { toast } = useToast();

  if (!result) {
    return (
      <Card className="w-full">
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle className="text-2xl font-bold text-gray-900">Prediction Results</CardTitle>
            <div className="flex space-x-2">
              <Button variant="outline" disabled>
                <Download className="mr-2 h-4 w-4" />
                JSON
              </Button>
              <Button variant="outline" disabled>
                <Download className="mr-2 h-4 w-4" />
                CSV
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="text-center py-12">
            <TrendingUp className="mx-auto h-12 w-12 text-gray-300 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No predictions yet</h3>
            <p className="text-gray-500">Fill in the parameters and click "Predict Peak Voltage" to see results</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-2xl font-bold text-gray-900">Prediction Results</CardTitle>
          <div className="flex space-x-2">
            <Button variant="outline" onClick={onExportJson}>
              <Download className="mr-2 h-4 w-4" />
              JSON
            </Button>
            <Button variant="outline" onClick={onExportCsv}>
              <Download className="mr-2 h-4 w-4" />
              CSV
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Peak Voltage Result */}
        <div className="gradient-primary rounded-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-medium mb-2">Peak Voltage Prediction</h3>
              <div className="text-3xl font-bold">{result.U_max?.toFixed(2) || '--'}</div>
              <div className="text-sm opacity-90">Volts (V)</div>
            </div>
            <Bolt className="h-16 w-16 opacity-20" />
          </div>
        </div>

        {/* Detailed Results */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-medium text-gray-900 mb-3">System Parameters</h4>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">kW Surplus:</span>
                <span className="font-mono">{result.kW_surplus?.toFixed(2) || '--'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">kWp:</span>
                <span className="font-mono">{result.kWp?.toFixed(2) || '--'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">PV Systems:</span>
                <span className="font-mono">{result.pvsystems_count || '--'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">UW:</span>
                <span className="font-mono">{result.UW?.toFixed(2) || '--'}</span>
              </div>
            </div>
          </div>

          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-medium text-gray-900 mb-3">Environmental</h4>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Temperature:</span>
                <span className="font-mono">{result.ta?.toFixed(1) || '--'}°C</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Irradiance:</span>
                <span className="font-mono">{result.gh?.toFixed(1) || '--'} W/m²</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Diffuse:</span>
                <span className="font-mono">{result.dd?.toFixed(1) || '--'} W/m²</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Rainfall:</span>
                <span className="font-mono">{result.rr?.toFixed(1) || '--'} mm</span>
              </div>
            </div>
          </div>
        </div>

        {/* Timestamp */}
        <div className="text-sm text-gray-500 flex items-center">
          <Clock className="mr-2 h-4 w-4" />
          Predicted on: {new Date().toLocaleString()}
        </div>
      </CardContent>
    </Card>
  );
}
