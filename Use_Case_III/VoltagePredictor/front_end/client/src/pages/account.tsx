import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { User, Key, CreditCard, LogOut, Settings } from "lucide-react";
import ApiKeyManagement from "@/components/account/api-key-management";
import BillingDashboard from "@/components/account/billing-dashboard";
import ProtectedRoute from "@/components/auth/protected-route";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

export default function Account() {
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
      window.location.href = '/';
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
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <User className="text-primary text-2xl mr-3" />
              <div>
                <h1 className="text-xl font-bold text-gray-900 dark:text-white">Account Dashboard</h1>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Welcome back, {user?.username}
                </p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              {balance && (
                <Badge variant="outline" className="text-sm" data-testid="badge-user-balance">
                  {balance.current_balance} tokens
                </Badge>
              )}
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
        {/* User Info Card */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <Settings className="h-5 w-5" />
              <span>Account Information</span>
            </CardTitle>
            <CardDescription>
              Your account details and current status
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Username</p>
                <p className="text-lg font-semibold" data-testid="text-user-username">
                  {user?.username}
                </p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">User ID</p>
                <p className="text-lg font-semibold font-mono" data-testid="text-user-id">
                  {user?.user_id}
                </p>
              </div>
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Login Message</p>
                <p className="text-lg font-semibold" data-testid="text-user-message">
                  {user?.message || 'Welcome!'}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Account Management Tabs */}
        <Tabs defaultValue="billing" className="w-full">
          <TabsList className="grid w-full grid-cols-2 mb-8">
            <TabsTrigger value="billing" className="flex items-center gap-2">
              <CreditCard className="h-4 w-4" />
              Billing & Usage
            </TabsTrigger>
            <TabsTrigger value="api-keys" className="flex items-center gap-2">
              <Key className="h-4 w-4" />
              API Keys
            </TabsTrigger>
          </TabsList>

          <TabsContent value="billing">
            <BillingDashboard />
          </TabsContent>

          <TabsContent value="api-keys">
            <ApiKeyManagement />
          </TabsContent>
        </Tabs>
      </div>
      </div>
    </ProtectedRoute>
  );
}