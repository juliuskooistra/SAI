// Simplified storage for local session management only
// All API interactions will be handled by external Peak Voltage API

export interface IStorage {
  // Local session management only
  setCurrentUser(user: any): void;
  getCurrentUser(): any;
  setCurrentApiKey(apiKey: string): void;
  getCurrentApiKey(): string | null;
  clearSession(): void;
}

export class SessionStorage implements IStorage {
  private currentUser: any = null;
  private currentApiKey: string | null = null;

  setCurrentUser(user: any): void {
    this.currentUser = user;
  }

  getCurrentUser(): any {
    return this.currentUser;
  }

  clearSession(): void {
    this.currentUser = null;
  }

  setCurrentApiKey(apiKey: string): void {
    this.currentApiKey = apiKey;
  }

  getCurrentApiKey(): string | null {
    return this.currentApiKey;
  }

  clearApiKey(): void {
    this.currentApiKey = null;
  }
}

export const storage = new SessionStorage();
