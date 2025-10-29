import type { Express } from "express";
import { createServer, type Server } from "http";
import { storage } from "./storage";

export async function registerRoutes(app: Express): Promise<Server> {
  // Simple session management endpoints for the frontend
  app.get("/api/session", (req, res) => {
    const user = storage.getCurrentUser();
    res.json({ user });
  });

  app.post("/api/session", (req, res) => {
    const { user } = req.body;
    storage.setCurrentUser(user);
    res.json({ success: true });
  });

  app.delete("/api/session", (req, res) => {
    storage.clearSession();
    res.json({ success: true });
  });


  app.get("/api/session/api_key", (req, res) => {
    const apiKey = storage.getCurrentApiKey();
    res.json({ apiKey });
  });

  app.post("/api/session/api_key", (req, res) => {
    const { apiKey } = req.body;
    storage.setCurrentApiKey(apiKey);
    res.json({ success: true });
  });

  app.delete("/api/session/api_key", (req, res) => {
    storage.clearApiKey();
    res.json({ success: true });
  });

  const httpServer = createServer(app);
  return httpServer;
}
