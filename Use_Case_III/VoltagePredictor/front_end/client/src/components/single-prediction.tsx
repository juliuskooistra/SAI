import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import PredictionForm from "./prediction-form";
import ResultsDisplay from "./results-display";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";

export default function SinglePrediction() {
  const [result, setResult] = useState<any>(null);
  const { toast } = useToast();

  const mutation = useMutation({
    mutationFn: async (formData: any) => {
      const requestData = {
        data: [formData],
        return_scaled: formData.return_scaled || false,
      };
      return api.predictPeakVoltages(requestData);
    },
    onSuccess: (data) => {
      setResult(data.data[0]);
      toast({
        title: "Success",
        description: "Peak voltage prediction completed successfully!",
      });
    },
    onError: (error) => {
      console.error('Prediction error:', error);
      toast({
        title: "Error",
        description: "Failed to get prediction. Please try again.",
        variant: "destructive",
      });
    },
  });

  const handleExportJson = () => {
    if (!result) return;
    const dataStr = JSON.stringify(result, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    const exportFileDefaultName = `peak_voltage_prediction_${new Date().toISOString().split('T')[0]}.json`;
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
    toast({
      title: "Success",
      description: "JSON export completed successfully!",
    });
  };

  const handleExportCsv = () => {
    if (!result) return;
    const headers = Object.keys(result).join(',');
    const values = Object.values(result).join(',');
    const csvContent = `${headers}\n${values}`;
    const dataUri = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csvContent);
    const exportFileDefaultName = `peak_voltage_prediction_${new Date().toISOString().split('T')[0]}.csv`;
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
    toast({
      title: "Success",
      description: "CSV export completed successfully!",
    });
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
      <PredictionForm 
        onSubmit={mutation.mutate} 
        isLoading={mutation.isPending}
      />
      
      <div className="space-y-6">
        {mutation.isError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {mutation.error instanceof Error ? mutation.error.message : 'An error occurred while processing your request.'}
            </AlertDescription>
          </Alert>
        )}
        
        <ResultsDisplay 
          result={result}
          onExportJson={handleExportJson}
          onExportCsv={handleExportCsv}
        />
      </div>
    </div>
  );
}
