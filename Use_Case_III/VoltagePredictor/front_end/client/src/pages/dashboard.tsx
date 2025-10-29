import { useState } from "react";
import { Bolt, Calculator, Table, History, User, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import SinglePrediction from "@/components/single-prediction";
import BatchProcessing from "@/components/batch-processing";
import PredictionHistory from "@/components/prediction-history";
import ProtectedRoute from "@/components/auth/protected-route";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { useQuery } from "@tanstack/react-query";

export default function Dashboard() {
  const { user } = useAuth();
  const { toast } = useToast();

  // Get current balance for logged in users
  const { data: balance } = useQuery({
    queryKey: ['/billing/balance'],
    queryFn: api.getBalance,
    enabled: !!user,
    retry: false,
  });

  const handleLogout = async () => {
    try {
      await api.clearSession();
      toast({
        title: "Logged Out",
        description: "You have been successfully logged out.",
      });
      window.location.reload();
    } catch (error) {
      toast({
        title: "Logout Error",
        description: "There was an error logging out. Please try again.",
        variant: "destructive",
      });
    }
  };

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-gray-50">
        {/* Header */}
        <header className="bg-white shadow-sm border-b border-gray-200 sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between items-center h-16">
              <div className="flex items-center">
                <Bolt className="text-primary text-2xl mr-3" />
                <h1 className="text-xl font-bold text-gray-900">Peak Voltage Predictor</h1>
              </div>
              <nav className="hidden md:flex space-x-8">
                <a href="/" className="text-primary font-medium">Dashboard</a>
                <a href="#predictions" className="text-gray-500 hover:text-gray-700">Predictions</a>
                <a href="#history" className="text-gray-500 hover:text-gray-700">History</a>
                <a href="#api-docs" className="text-gray-500 hover:text-gray-700">API Docs</a>
              </nav>
              <div className="flex items-center space-x-4">
                {balance && (
                  <Badge variant="outline" className="text-sm" data-testid="badge-user-balance">
                    {balance.current_balance} tokens
                  </Badge>
                )}
                {user && (
                  <span className="text-sm text-gray-600" data-testid="text-user-greeting">
                    Welcome, {user.username}
                  </span>
                )}
                <Button 
                  variant="outline"
                  onClick={() => window.location.href = '/account'}
                  data-testid="button-account"
                >
                  <User className="mr-2 h-4 w-4" />
                  Account
                </Button>
                <Button 
                  variant="outline"
                  onClick={handleLogout}
                  data-testid="button-logout"
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Logout
                </Button>
              </div>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Tabs defaultValue="single" className="w-full">
            <TabsList className="grid w-full grid-cols-3 mb-8">
              <TabsTrigger value="single" className="flex items-center gap-2">
                <Calculator className="h-4 w-4" />
                Single Prediction
              </TabsTrigger>
              <TabsTrigger value="batch" className="flex items-center gap-2">
                <Table className="h-4 w-4" />
                Batch Processing
              </TabsTrigger>
              <TabsTrigger value="history" className="flex items-center gap-2">
                <History className="h-4 w-4" />
                History
              </TabsTrigger>
            </TabsList>

            <TabsContent value="single">
              <SinglePrediction />
            </TabsContent>

            <TabsContent value="batch">
              <BatchProcessing />
            </TabsContent>

            <TabsContent value="history">
              <PredictionHistory />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </ProtectedRoute>
  );
}
