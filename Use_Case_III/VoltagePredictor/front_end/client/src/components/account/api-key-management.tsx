import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Key, Plus, Trash2, Copy, Eye, EyeOff } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { apiKeyGenerationSchema, type ApiKeyGeneration } from "@shared/schema";

export default function ApiKeyManagement() {
  const [showGenerateForm, setShowGenerateForm] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const { data: sessionData, isLoading: sessionLoading, error: sessionError } = useQuery({
    queryKey: ['/api/session'],
    queryFn: api.getSession,
    retry: false,
  });

  const userId = sessionData?.user.userId;
  const username = sessionData?.user.username;

  const form = useForm<ApiKeyGeneration>({
    resolver: zodResolver(apiKeyGenerationSchema),
    defaultValues: {
      username: username,
      password: "",
      api_key_name: "",
      expires_in_days: 30,
    },
  });

  const { data: apiKeys = [], isLoading, error } = useQuery({
    queryKey: ['/auth/my-keys', userId],
    queryFn: () => api.getMyApiKeys(userId),
    enabled: !!userId,
    retry: false,
  });

  const generateKeyMutation = useMutation({
    mutationFn: api.generateApiKey,
    onSuccess: (data) => {
      setGeneratedKey(data.api_key);
      setShowGenerateForm(false);
      form.reset();
      queryClient.invalidateQueries({ queryKey: ['/auth/my-keys'] });
      toast({
        title: "Success",
        description: "API key generated successfully!",
      });
    },
    onError: (error) => {
      toast({
        title: "Generation Failed",
        description: error instanceof Error ? error.message : "Failed to generate API key.",
        variant: "destructive",
      });
    },
  });

  const revokeKeyMutation = useMutation({
    mutationFn: api.revokeApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['/auth/my-keys'] });
      toast({
        title: "Success",
        description: "API key revoked successfully!",
      });
    },
    onError: (error) => {
      toast({
        title: "Revocation Failed",
        description: error instanceof Error ? error.message : "Failed to revoke API key.",
        variant: "destructive",
      });
    },
  });

  const onSubmit = (data: ApiKeyGeneration) => {
    generateKeyMutation.mutate(data);
  };

  const handleCopyKey = (key: string) => {
    navigator.clipboard.writeText(key);
    toast({
      title: "Copied",
      description: "API key copied to clipboard!",
    });
  };

  const handleUseKey = async (key: string) => {
    await api.setApiKey(key)

    toast({
      title: "API Key Set",
      description: "This API key is now being used for predictions!",
    });
  };

  return (
    <div className="space-y-6">
      {/* Generated Key Display */}
      {generatedKey && (
        <Alert>
          <Key className="h-4 w-4" />
          <AlertDescription>
            <div className="space-y-2">
              <p className="font-medium">Your new API key has been generated:</p>
              <div className="flex items-center space-x-2">
                <code className="bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded text-sm flex-1">
                  {generatedKey}
                </code>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleCopyKey(generatedKey)}
                  data-testid="button-copy-generated-key"
                >
                  <Copy className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  onClick={() => handleUseKey(generatedKey)}
                  data-testid="button-use-generated-key"
                >
                  Use This Key
                </Button>
              </div>
              <p className="text-sm text-gray-600">
                Save this key securely. You won't be able to see it again.
              </p>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {/* API Key List */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <div>
              <CardTitle>API Keys</CardTitle>
              <CardDescription>
                Manage your API keys for accessing the Peak Voltage API
              </CardDescription>
            </div>
            <Button
              onClick={() => setShowGenerateForm(!showGenerateForm)}
              data-testid="button-toggle-generate-form"
            >
              <Plus className="mr-2 h-4 w-4" />
              Generate New Key
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {/* Generate Form */}
          {showGenerateForm && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="text-lg">Generate New API Key</CardTitle>
                <CardDescription>
                  Enter your credentials to create a new API key
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Form {...form}>
                  <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <FormField
                        control={form.control}
                        name="username"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Username</FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                placeholder="Your username"
                                data-testid="input-api-username"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="password"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Password</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <Input
                                  {...field}
                                  type={showPassword ? "text" : "password"}
                                  autoComplete="password"
                                  placeholder="Your password"
                                  data-testid="input-api-password"
                                />
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="absolute right-0 top-0 h-full px-3 py-2 hover:bg-transparent"
                                  onClick={() => setShowPassword(!showPassword)}
                                  data-testid="button-toggle-api-password"
                                >
                                  {showPassword ? (
                                    <EyeOff className="h-4 w-4" />
                                  ) : (
                                    <Eye className="h-4 w-4" />
                                  )}
                                </Button>
                              </div>
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="api_key_name"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Key Name</FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                placeholder="e.g., Production API Key"
                                data-testid="input-api-key-name"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="expires_in_days"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Expires In (Days)</FormLabel>
                            <FormControl>
                              <Input
                                {...field}
                                type="number"
                                min="1"
                                max="365"
                                onChange={(e) => field.onChange(parseInt(e.target.value) || 30)}
                                data-testid="input-api-expires-days"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>

                    <div className="flex space-x-2">
                      <Button
                        type="submit"
                        disabled={generateKeyMutation.isPending}
                        data-testid="button-generate-api-key"
                      >
                        {generateKeyMutation.isPending ? "Generating..." : "Generate Key"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => setShowGenerateForm(false)}
                        data-testid="button-cancel-generate"
                      >
                        Cancel
                      </Button>
                    </div>
                  </form>
                </Form>
              </CardContent>
            </Card>
          )}

          {/* API Keys Table */}
          {isLoading ? (
            <div className="text-center py-8">Loading API keys...</div>
          ) : error ? (
            <Alert variant="destructive">
              <AlertDescription>
                Failed to load API keys. Please try again.
              </AlertDescription>
            </Alert>
          ) : apiKeys.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No API keys found. Generate your first key to get started.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Last Used</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {apiKeys.map((key: any) => (
                  <TableRow key={key.api_key_name}>
                    <TableCell className="font-medium" data-testid={`text-key-name-${key.api_key_name}`}>
                      {key.api_key_name}
                    </TableCell>
                    <TableCell data-testid={`text-key-created-${key.api_key_name}`}>
                      {new Date(key.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell data-testid={`text-key-used-${key.api_key_name}`}>
                      {key.last_used_at 
                        ? new Date(key.last_used_at).toLocaleDateString()
                        : "Never"
                      }
                    </TableCell>
                    <TableCell>
                      <Badge 
                        variant={key.is_active ? "default" : "secondary"}
                        data-testid={`badge-key-status-${key.api_key_name}`}
                      >
                        {key.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => revokeKeyMutation.mutate(key.api_key_name)}
                        disabled={revokeKeyMutation.isPending}
                        data-testid={`button-revoke-${key.api_key_name}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}