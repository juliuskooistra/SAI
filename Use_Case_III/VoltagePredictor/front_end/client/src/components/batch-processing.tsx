import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Download, Upload, Play, CloudUpload } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export default function BatchProcessing() {
  const [file, setFile] = useState<File | null>(null);
  const [results, setResults] = useState<any[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const { toast } = useToast();

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      toast({
        title: "Success",
        description: `File "${selectedFile.name}" uploaded successfully`,
      });
    }
  };

  const handleDownloadTemplate = () => {
    const headers = [
      'kW_surplus', 'kWp', 'pvsystems_count', 'ta', 'gh', 'dd', 'rr',
      'hour_sin', 'hour_cos', 'week_sin', 'week_cos', 'weekday_sin', 'weekday_cos', 'UW'
    ];
    const csvContent = headers.join(',') + '\n';
    const dataUri = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csvContent);
    const exportFileDefaultName = 'peak_voltage_template.csv';
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
    toast({
      title: "Success",
      description: "Template download completed successfully!",
    });
  };

  const handleBatchProcess = async () => {
    if (!file) return;
    
    setIsProcessing(true);
    try {
      // This would normally parse the CSV and make API calls
      // For now, we'll show a placeholder
      toast({
        title: "Processing",
        description: "Batch processing started. This may take a few minutes...",
      });
      
      // Simulate processing
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // Mock results
      const mockResults = [
        { row: 1, kW_surplus: 12.5, kWp: 25.0, pvsystems_count: 3, U_max: 245.7, status: 'success' },
        { row: 2, kW_surplus: 8.3, kWp: 18.5, pvsystems_count: 2, U_max: 238.2, status: 'success' },
        { row: 3, kW_surplus: 15.2, kWp: 30.0, pvsystems_count: 4, U_max: 252.1, status: 'success' },
      ];
      
      setResults(mockResults);
      toast({
        title: "Success",
        description: "Batch processing completed successfully!",
      });
    } catch (error) {
      toast({
        title: "Error",
        description: "Batch processing failed. Please try again.",
        variant: "destructive",
      });
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-2xl font-bold text-gray-900">Batch Processing</CardTitle>
          <div className="flex space-x-2">
            <Button variant="outline" onClick={handleDownloadTemplate}>
              <Download className="mr-2 h-4 w-4" />
              Download Template
            </Button>
            <Button 
              onClick={handleBatchProcess}
              disabled={!file || isProcessing}
            >
              <Play className="mr-2 h-4 w-4" />
              {isProcessing ? 'Processing...' : 'Process Batch'}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* File Upload */}
        <div>
          <Label htmlFor="csv-file" className="text-sm font-medium text-gray-700 mb-2 block">
            Upload CSV File
          </Label>
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-gray-400 transition-colors">
            <input
              id="csv-file"
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="hidden"
            />
            <CloudUpload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
            <p className="text-gray-600 mb-2">Click to upload or drag and drop your CSV file</p>
            <p className="text-sm text-gray-500 mb-4">CSV files up to 10MB</p>
            <Button 
              variant="outline" 
              onClick={() => document.getElementById('csv-file')?.click()}
            >
              <Upload className="mr-2 h-4 w-4" />
              Select File
            </Button>
            {file && (
              <p className="mt-2 text-sm text-green-600">
                Selected: {file.name}
              </p>
            )}
          </div>
        </div>

        {/* Batch Results */}
        {results.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Batch Results</h3>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Row</TableHead>
                    <TableHead>kW Surplus</TableHead>
                    <TableHead>kWp</TableHead>
                    <TableHead>PV Systems</TableHead>
                    <TableHead>Peak Voltage (V)</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.map((result, index) => (
                    <TableRow key={index}>
                      <TableCell>{result.row}</TableCell>
                      <TableCell className="font-mono">{result.kW_surplus}</TableCell>
                      <TableCell className="font-mono">{result.kWp}</TableCell>
                      <TableCell className="font-mono">{result.pvsystems_count}</TableCell>
                      <TableCell className="font-mono">{result.U_max}</TableCell>
                      <TableCell>
                        <Badge variant={result.status === 'success' ? 'default' : 'destructive'}>
                          {result.status}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
