# Peak Voltage Predictor Application

## Overview

This is a frontend web application for energy sector professionals to access and monetize a peak voltage prediction ML model through an intuitive interface. The application connects to an external Peak Voltage API that handles authentication, billing, and ML predictions, while providing a professional dashboard for users to manage their accounts and make predictions.

## User Preferences

Preferred communication style: Simple, everyday language.

## Recent Changes (December 26, 2024)

- **Architecture Update**: Transitioned from full-stack to frontend-only application
- **External API Integration**: Connected to external Peak Voltage API for all data operations
- **Authentication System**: Added complete user registration, login, and session management
- **Account Management**: Built comprehensive account dashboard with billing and API key management
- **Billing Dashboard**: Integrated token purchase system and usage statistics
- **API Key Management**: Added interface for generating, viewing, and revoking API keys
- **Local Storage**: Implemented prediction history using browser local storage
- **Error Handling**: Enhanced error messages for authentication and billing issues

## System Architecture

### Frontend Architecture
- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite for fast development and optimized builds
- **Styling**: Tailwind CSS with shadcn/ui component library
- **State Management**: TanStack Query (React Query) for server state
- **Routing**: Wouter for lightweight client-side routing
- **Forms**: React Hook Form with Zod validation

### Backend Architecture (Minimal - Frontend Focused)
- **Framework**: Express.js with TypeScript (minimal server for static hosting)
- **Session Management**: Simple in-memory session storage for development
- **External API Integration**: Complete integration with Peak Voltage API for all operations
- **Local Storage**: Browser-based prediction history and session management

### Data Management
- **External API**: All user data, billing, and predictions handled by Peak Voltage API
- **Local Storage**: Prediction history cached locally for performance
- **Session Management**: Simple session storage for logged-in user state
- **No Database**: Removed PostgreSQL dependency in favor of external API

## Key Components

### Frontend Components
1. **Dashboard**: Main application interface with tabbed navigation
2. **Account Management**: Complete authentication and account dashboard
3. **Login/Register Forms**: User authentication interface
4. **API Key Management**: Generate, view, and revoke API keys
5. **Billing Dashboard**: Token purchasing and usage statistics
6. **Single Prediction**: Form-based individual prediction interface
7. **Batch Processing**: CSV upload and bulk prediction processing
8. **Prediction History**: Historical data display and export functionality
9. **Results Display**: Formatted prediction results with export options

### External API Integration
1. **Authentication Endpoints**: User registration, login, and API key management
2. **Billing Endpoints**: Token purchasing, balance checking, and usage statistics
3. **Prediction Endpoints**: Peak voltage ML model predictions
4. **Rate Limiting**: API rate limit status and monitoring
5. **Session Management**: Simple local session storage for user state

### UI/UX Features
- Responsive design with mobile-first approach
- Real-time form validation
- Loading states and error handling
- Toast notifications for user feedback
- Export functionality (JSON, CSV)
- File upload with drag-and-drop support

## Data Flow

1. **Single Prediction Flow**:
   - User fills form with electrical parameters
   - Form validation using Zod schemas
   - API call to external prediction service
   - Results stored in database and displayed to user

2. **Batch Processing Flow**:
   - User uploads CSV file with multiple predictions
   - File parsing and validation
   - Bulk API calls to external service
   - Results aggregation and storage
   - Download processed results

3. **History Management**:
   - All predictions stored with timestamps
   - User can view, filter, and export historical data
   - Data persistence across sessions

## External Dependencies

### Core Dependencies
- **Database**: Neon Database (PostgreSQL serverless)
- **UI Components**: Radix UI primitives via shadcn/ui
- **Validation**: Zod for schema validation
- **HTTP Client**: Native fetch API
- **External API**: Peak voltage prediction service

### Development Tools
- **TypeScript**: Type safety across the stack
- **ESLint/Prettier**: Code quality and formatting
- **Vite**: Development server and build tool
- **Replit Integration**: Development environment support

## Deployment Strategy

### Build Process
1. **Frontend**: Vite builds React app to `dist/public`
2. **Backend**: esbuild bundles Express server to `dist/index.js`
3. **Database**: Drizzle migrations applied via `db:push`

### Environment Configuration
- `VITE_PEAK_VOLTAGE_API_URL`: External Peak Voltage API base URL
- `NODE_ENV`: Environment flag (development/production)
- API keys stored in browser localStorage for authenticated requests
- No database configuration needed (external API handles all data)

### Production Setup
- Static files served from `dist/public`
- Express server handles API routes and fallback to SPA
- Database migrations managed through Drizzle
- Session storage in PostgreSQL for scalability

### Development Features
- Hot module replacement for fast development
- Development-only error overlays
- Replit-specific development integrations
- Automatic TypeScript compilation