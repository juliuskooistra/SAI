import type { 
  PeakVoltageListRequest, 
  UserRegistration, 
  UserLogin, 
  ApiKeyGeneration, 
  TokenPurchase 
} from "@shared/schema";

// Configuration for external Peak Voltage API
const API_BASE_URL = import.meta.env.VITE_PEAK_VOLTAGE_API_URL || 'http://localhost:8000';

// Helper function to make authenticated requests
async function makeApiRequest(endpoint: string, options: RequestInit = {}) {
  const apiKey = await api.getApiKey();

  const headers = {
    'Content-Type': 'application/json',
    ...(apiKey && { 'Authorization': `Bearer ${apiKey.apiKey}` }),
    ...options.headers,
  };

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorData = await response.text();
    throw new Error(`API Error ${response.status}: ${errorData}`);
  }

  return response.json();
}

// Helper function to make unauthenticated requests
async function makeRequest(endpoint: string, options: RequestInit = {}) {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  });

  if (!response.ok) {
    const errorData = await response.text();
    throw new Error(`Request Error ${response.status}: ${errorData}`);
  }

  return response.json();
}

// Helper function for session management
async function makeSessionRequest(endpoint: string, options: RequestInit = {}) {
  const response = await fetch(endpoint, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`Session Error ${response.status}`);
  }

  return response.json();
}

export const api = {
  // Authentication
  async register(data: UserRegistration) {
    return makeRequest('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async login(data: UserLogin) {
    return makeRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // API Key Management
  async generateApiKey(data: ApiKeyGeneration) {
    return makeRequest('/auth/generate-key', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getMyApiKeys(userId: number) {
    return makeApiRequest('/auth/my-keys', {
      method: 'GET',
      body: JSON.stringify({
        user_id: userId
      })
    });
  },

  async revokeApiKey(keyName: string) {
    return makeApiRequest(`/auth/revoke-key/${keyName}`, {
      method: 'DELETE',
    });
  },

  // Billing
  async purchaseTokens(data: TokenPurchase) {
    return makeApiRequest('/billing/purchase-tokens', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getBalance() {
    return makeApiRequest('/billing/balance');
  },

  async getUsageStats(days?: number) {
    const query = days ? `?days=${days}` : '';
    return makeApiRequest(`/billing/usage-stats${query}`);
  },

  async getRateLimitStatus() {
    return makeApiRequest('/billing/rate-limit-status');
  },

  // Peak Voltage Predictions
  async predictPeakVoltages(data: PeakVoltageListRequest) {
    return makeApiRequest('/api/peak-voltages', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getPredictions() {
    // TODO: Fix to right path
    return makeApiRequest('/api/predictions',
      {
        method: 'GET',
      }
    );
  },


  // Local session management
  async getSession() {
    return makeSessionRequest('/api/session');
  },

  async setSession(user: any) {
    return makeSessionRequest('/api/session', {
      method: 'POST',
      body: JSON.stringify({ user }),
    });
  },

  async clearSession() {
    return makeSessionRequest('/api/session', {
      method: 'DELETE',
    });
  },

  // Local API key management
  async getApiKey() {
    return makeSessionRequest('/api/session/api_key');
  },

  async setApiKey(apiKey: string) {
    console.log(apiKey)
    return makeSessionRequest('/api/session/api_key', {
      method: 'POST',
      body: JSON.stringify({ apiKey }),
    });
  },

  async clearApiKey() {
    return makeSessionRequest('/api/session/api_key', {
      method: 'DELETE',
    });
  },
};
