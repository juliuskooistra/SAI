import { pgTable, text, serial, integer, boolean, timestamp, decimal } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";

export const users = pgTable("users", {
  id: serial("id").primaryKey(),
  username: text("username").notNull().unique(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  createdAt: timestamp("created_at").defaultNow(),
  updatedAt: timestamp("updated_at").defaultNow(),
});

export const apiKeys = pgTable("api_keys", {
  id: serial("id").primaryKey(),
  userId: integer("user_id").references(() => users.id),
  keyName: text("key_name").notNull(),
  keyHash: text("key_hash").notNull(),
  isActive: boolean("is_active").default(true),
  createdAt: timestamp("created_at").defaultNow(),
  expiresAt: timestamp("expires_at"),
  lastUsedAt: timestamp("last_used_at"),
});

export const userBalance = pgTable("user_balance", {
  id: serial("id").primaryKey(),
  userId: integer("user_id").references(() => users.id).notNull(),
  currentBalance: decimal("current_balance", { precision: 15, scale: 2 }).default("0"),
  totalPurchased: decimal("total_purchased", { precision: 15, scale: 2 }).default("0"),
  totalUsed: decimal("total_used", { precision: 15, scale: 2 }).default("0"),
  updatedAt: timestamp("updated_at").defaultNow(),
});

export const usageStats = pgTable("usage_stats", {
  id: serial("id").primaryKey(),
  userId: integer("user_id").references(() => users.id),
  apiKeyId: integer("api_key_id").references(() => apiKeys.id),
  endpoint: text("endpoint").notNull(),
  tokensConsumed: decimal("tokens_consumed", { precision: 10, scale: 2 }),
  createdAt: timestamp("created_at").defaultNow(),
});

export const predictions = pgTable("predictions", {
  id: serial("id").primaryKey(),
  userId: integer("user_id").references(() => users.id),
  type: text("type").notNull(), // 'single' or 'batch'
  createdAt: timestamp("created_at").defaultNow(),
  // Input parameters
  kW_surplus: decimal("kw_surplus", { precision: 10, scale: 2 }),
  kWp: decimal("kwp", { precision: 10, scale: 2 }),
  pvsystems_count: integer("pvsystems_count"),
  ta: decimal("ta", { precision: 10, scale: 2 }),
  gh: decimal("gh", { precision: 10, scale: 2 }),
  dd: decimal("dd", { precision: 10, scale: 2 }),
  rr: decimal("rr", { precision: 10, scale: 2 }),
  hour_sin: decimal("hour_sin", { precision: 10, scale: 6 }),
  hour_cos: decimal("hour_cos", { precision: 10, scale: 6 }),
  week_sin: decimal("week_sin", { precision: 10, scale: 6 }),
  week_cos: decimal("week_cos", { precision: 10, scale: 6 }),
  weekday_sin: decimal("weekday_sin", { precision: 10, scale: 6 }),
  weekday_cos: decimal("weekday_cos", { precision: 10, scale: 6 }),
  UW: decimal("uw", { precision: 10, scale: 2 }),
  return_scaled: boolean("return_scaled").default(false),
  // Result
  U_max: decimal("u_max", { precision: 10, scale: 2 }),
});

// User registration and login schemas
export const userRegistrationSchema = z.object({
  username: z.string().min(3, "Username must be at least 3 characters"),
  email: z.string().email("Valid email is required").optional(),
  password: z.string().min(6, "Password must be at least 6 characters"),
});

export const userLoginSchema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});

// API Key management schemas
export const apiKeyGenerationSchema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
  api_key_name: z.string().min(1, "API key name is required"),
  expires_in_days: z.number().min(1).max(365).default(30),
});

export const insertApiKeySchema = createInsertSchema(apiKeys).omit({
  id: true,
  createdAt: true,
  lastUsedAt: true,
});

// Billing schemas
export const tokenPurchaseSchema = z.object({
  amount: z.number().positive(),
  payment_method: z.string().optional().default("demo"),
});

export const insertUserBalanceSchema = createInsertSchema(userBalance).omit({
  id: true,
  updatedAt: true,
});

export const insertUsageStatsSchema = createInsertSchema(usageStats).omit({
  id: true,
  createdAt: true,
});

// Prediction schemas
export const insertPredictionSchema = createInsertSchema(predictions).omit({
  id: true,
  userId: true,
  createdAt: true,
  U_max: true,
});

export const peakVoltageRequestSchema = z.object({
  kW_surplus: z.number().optional(),
  kWp: z.number().optional(),
  pvsystems_count: z.number().optional(),
  ta: z.number().optional(),
  gh: z.number().optional(),
  dd: z.number().optional(),
  rr: z.number().optional(),
  hour_sin: z.number().optional(),
  hour_cos: z.number().optional(),
  week_sin: z.number().optional(),
  week_cos: z.number().optional(),
  weekday_sin: z.number().optional(),
  weekday_cos: z.number().optional(),
  UW: z.number().optional(),
});

export const peakVoltageListRequestSchema = z.object({
  data: z.array(peakVoltageRequestSchema),
  return_scaled: z.boolean().optional().default(false),
});

// Type exports
export type UserRegistration = z.infer<typeof userRegistrationSchema>;
export type UserLogin = z.infer<typeof userLoginSchema>;
export type ApiKeyGeneration = z.infer<typeof apiKeyGenerationSchema>;
export type TokenPurchase = z.infer<typeof tokenPurchaseSchema>;

// Type definitions for external API responses
export type AuthResponse = {
  message: string;
  user_id: string;
  username: string;
};

export type User = typeof users.$inferSelect;
export type ApiKey = typeof apiKeys.$inferSelect;
export type UserBalance = typeof userBalance.$inferSelect;
export type UsageStats = typeof usageStats.$inferSelect;
export type Prediction = typeof predictions.$inferSelect;

export type InsertUser = z.infer<typeof userRegistrationSchema>;
export type InsertApiKey = z.infer<typeof insertApiKeySchema>;
export type InsertUserBalance = z.infer<typeof insertUserBalanceSchema>;
export type InsertUsageStats = z.infer<typeof insertUsageStatsSchema>;
export type InsertPrediction = z.infer<typeof insertPredictionSchema>;

export type PeakVoltageRequest = z.infer<typeof peakVoltageRequestSchema>;
export type PeakVoltageListRequest = z.infer<typeof peakVoltageListRequestSchema>;
