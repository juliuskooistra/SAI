import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Download, Filter, Eye } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

export default function PredictionHistory() {
  const { toast } = useToast();
  
  const { data: predictions = [], isLoading, error } = useQuery({
    queryKey: ['/api/predictions'],
    queryFn: () => api.getPredictions(),
  });

  const handleExportAll = () => {
    if (predictions.length === 0) return;
    
    const headers = ['Date', 'Type', 'Peak Voltage', 'kW Surplus', 'kWp', 'PV Systems'];
    const csvContent = [
      headers.join(','),
      ...predictions.map((p: any) => [
        new Date(p.createdAt).toLocaleString(),
        p.type,
        p.U_max || '--',
        p.kW_surplus || '--',
        p.kWp || '--',
        p.pvsystems_count || '--'
      ].join(','))
    ].join('\n');
    
    const dataUri = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csvContent);
    const exportFileDefaultName = `prediction_history_${new Date().toISOString().split('T')[0]}.csv`;
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
    
    toast({
      title: "Success",
      description: "History export completed successfully!",
    });
  };

  if (isLoading) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-gray-900">Prediction History</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-2xl font-bold text-gray-900">Prediction History</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-12">
            <p className="text-red-600">Failed to load prediction history. Please try again.</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-2xl font-bold text-gray-900">Prediction History</CardTitle>
          <div className="flex space-x-2">
            <Button variant="outline">
              <Filter className="mr-2 h-4 w-4" />
              Filter
            </Button>
            <Button variant="outline" onClick={handleExportAll}>
              <Download className="mr-2 h-4 w-4" />
              Export All
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {predictions.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-gray-500">No predictions found. Make your first prediction to see history.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Peak Voltage</TableHead>
                  <TableHead>kW Surplus</TableHead>
                  <TableHead>kWp</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {predictions.map((prediction: any) => (
                  <TableRow key={prediction.id}>
                    <TableCell className="text-sm">
                      {new Date(prediction.createdAt).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant={prediction.type === 'single' ? 'default' : 'secondary'}>
                        {prediction.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono">
                      {prediction.U_max ? `${parseFloat(prediction.U_max).toFixed(2)} V` : '--'}
                    </TableCell>
                    <TableCell className="font-mono">
                      {prediction.kW_surplus ? parseFloat(prediction.kW_surplus).toFixed(2) : '--'}
                    </TableCell>
                    <TableCell className="font-mono">
                      {prediction.kWp ? parseFloat(prediction.kWp).toFixed(2) : '--'}
                    </TableCell>
                    <TableCell>
                      <div className="flex space-x-2">
                        <Button variant="ghost" size="sm">
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm">
                          <Download className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
