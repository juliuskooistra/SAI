import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { CreditCard, DollarSign, TrendingUp, Activity, Clock } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { tokenPurchaseSchema, type TokenPurchase } from "@shared/schema";

export default function BillingDashboard() {
  const [showPurchaseForm, setShowPurchaseForm] = useState(false);
  const [usageStatsDays, setUsageStatsDays] = useState(30);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const form = useForm<TokenPurchase>({
    resolver: zodResolver(tokenPurchaseSchema),
    defaultValues: {
      amount: 100,
      payment_method: "demo",
    },
  });

  // Queries
  const { data: balance, isLoading: balanceLoading } = useQuery({
    queryKey: ['/billing/balance'],
    queryFn: api.getBalance,
    retry: false,
  });

  const { data: usageStats, isLoading: usageLoading } = useQuery({
    queryKey: ['/billing/usage-stats', usageStatsDays],
    queryFn: () => api.getUsageStats(usageStatsDays),
    retry: false,
  });

  const { data: rateLimitStatus } = useQuery({
    queryKey: ['/billing/rate-limit-status'],
    queryFn: api.getRateLimitStatus,
    retry: false,
  });

  // Mutations
  const purchaseTokensMutation = useMutation({
    mutationFn: api.purchaseTokens,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['/billing/balance'] });
      queryClient.invalidateQueries({ queryKey: ['/billing/usage-stats'] });
      setShowPurchaseForm(false);
      form.reset();
      toast({
        title: "Success",
        description: "Tokens purchased successfully!",
      });
    },
    onError: (error) => {
      toast({
        title: "Purchase Failed",
        description: error instanceof Error ? error.message : "Failed to purchase tokens.",
        variant: "destructive",
      });
    },
  });

  const onSubmit = (data: TokenPurchase) => {
    purchaseTokensMutation.mutate(data);
  };

  return (
    <div className="space-y-6">
      {/* Balance Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Current Balance</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold" data-testid="text-current-balance">
              {balanceLoading ? "..." : balance?.current_balance || "0"} tokens
            </div>
            <p className="text-xs text-muted-foreground">
              Available for predictions
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Purchased</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold" data-testid="text-total-purchased">
              {balanceLoading ? "..." : balance?.total_purchased || "0"} tokens
            </div>
            <p className="text-xs text-muted-foreground">
              Lifetime purchases
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Used</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold" data-testid="text-total-used">
              {balanceLoading ? "..." : balance?.total_used || "0"} tokens
            </div>
            <p className="text-xs text-muted-foreground">
              Lifetime usage
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Purchase Tokens */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <div>
              <CardTitle>Purchase Tokens</CardTitle>
              <CardDescription>
                Buy tokens to make predictions with the Peak Voltage API
              </CardDescription>
            </div>
            <Button
              onClick={() => setShowPurchaseForm(!showPurchaseForm)}
              data-testid="button-toggle-purchase-form"
            >
              <CreditCard className="mr-2 h-4 w-4" />
              Buy Tokens
            </Button>
          </div>
        </CardHeader>
        {showPurchaseForm && (
          <CardContent>
            <Form {...form}>
              <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="amount"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Number of Tokens</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="number"
                            min="1"
                            placeholder="100"
                            onChange={(e) => field.onChange(parseFloat(e.target.value) || 100)}
                            data-testid="input-token-amount"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="payment_method"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Payment Method</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger data-testid="select-payment-method">
                              <SelectValue placeholder="Select payment method" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="demo">Demo (Test Mode)</SelectItem>
                            <SelectItem value="credit_card">Credit Card</SelectItem>
                            <SelectItem value="paypal">PayPal</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <div className="flex space-x-2">
                  <Button
                    type="submit"
                    disabled={purchaseTokensMutation.isPending}
                    data-testid="button-purchase-tokens"
                  >
                    {purchaseTokensMutation.isPending ? "Processing..." : "Purchase Tokens"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setShowPurchaseForm(false)}
                    data-testid="button-cancel-purchase"
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            </Form>
          </CardContent>
        )}
      </Card>

      {/* Usage Statistics */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <div>
              <CardTitle>Usage Statistics</CardTitle>
              <CardDescription>
                Track your API usage and token consumption
              </CardDescription>
            </div>
            <Select value={usageStatsDays.toString()} onValueChange={(value) => setUsageStatsDays(parseInt(value))}>
              <SelectTrigger className="w-32" data-testid="select-usage-days">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="7">Last 7 days</SelectItem>
                <SelectItem value="30">Last 30 days</SelectItem>
                <SelectItem value="90">Last 90 days</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {usageLoading ? (
            <div className="text-center py-8">Loading usage statistics...</div>
          ) : usageStats ? (
            <div className="space-y-6">
              {/* Summary Stats */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center space-x-2">
                    <Activity className="h-5 w-5 text-blue-500" />
                    <div>
                      <p className="text-sm text-gray-600 dark:text-gray-400">Total Requests</p>
                      <p className="text-2xl font-bold" data-testid="text-total-requests">
                        {usageStats.total_requests}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4">
                  <div className="flex items-center space-x-2">
                    <DollarSign className="h-5 w-5 text-green-500" />
                    <div>
                      <p className="text-sm text-gray-600 dark:text-gray-400">Tokens Consumed</p>
                      <p className="text-2xl font-bold" data-testid="text-tokens-consumed">
                        {usageStats.total_tokens_consumed}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Endpoint Breakdown */}
              {usageStats.endpoint_breakdown && usageStats.endpoint_breakdown.length > 0 && (
                <div>
                  <h4 className="text-lg font-semibold mb-4">Endpoint Usage Breakdown</h4>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Endpoint</TableHead>
                        <TableHead>Requests</TableHead>
                        <TableHead>Tokens Used</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {usageStats.endpoint_breakdown.map((endpoint: any, index: number) => (
                        <TableRow key={index}>
                          <TableCell className="font-medium" data-testid={`text-endpoint-${index}`}>
                            {endpoint.endpoint}
                          </TableCell>
                          <TableCell data-testid={`text-endpoint-requests-${index}`}>
                            {endpoint.requests}
                          </TableCell>
                          <TableCell data-testid={`text-endpoint-tokens-${index}`}>
                            {endpoint.tokens}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No usage data available for the selected period.
            </div>
          )}
        </CardContent>
      </Card>

      {/* Rate Limit Status */}
      {rateLimitStatus && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <Clock className="h-5 w-5" />
              <span>Rate Limit Status</span>
            </CardTitle>
            <CardDescription>
              Current API rate limit information
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
                <p className="text-sm font-medium text-blue-600 dark:text-blue-400">Limits</p>
                <pre className="text-xs mt-2 text-blue-800 dark:text-blue-200" data-testid="text-rate-limits">
                  {JSON.stringify(rateLimitStatus.limits, null, 2)}
                </pre>
              </div>
              
              <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-lg p-4">
                <p className="text-sm font-medium text-yellow-600 dark:text-yellow-400">Current Usage</p>
                <pre className="text-xs mt-2 text-yellow-800 dark:text-yellow-200" data-testid="text-current-usage">
                  {JSON.stringify(rateLimitStatus.current_usage, null, 2)}
                </pre>
              </div>
              
              <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4">
                <p className="text-sm font-medium text-green-600 dark:text-green-400">Remaining</p>
                <pre className="text-xs mt-2 text-green-800 dark:text-green-200" data-testid="text-remaining-usage">
                  {JSON.stringify(rateLimitStatus.remaining, null, 2)}
                </pre>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}