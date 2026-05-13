export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: {
    code: string;
    message: string;
    recoverable: boolean;
  };
}

export interface User {
  id: number;
  username: string;
  display_name: string;
}

export interface ScheduleItem {
  type: "travel" | "activity" | "restaurant";
  name: string;
  location: string;
  start_time: string;
  end_time: string;
  reason: string;
  typeLabel?: string;
  transport_mode?: string;
  travel_minutes?: number;
}

export interface RouteOption {
  mode: string;
  duration_minutes: number;
  distance_km: number;
  estimated_cost: number;
  selected?: boolean;
}

export interface PendingAction {
  action_id: string;
  type: "book_activity" | "reserve_restaurant" | "send_notification";
  target: string;
  payload: Record<string, unknown>;
}

export interface Plan {
  plan_id: string;
  title: string;
  summary: string;
  schedule: ScheduleItem[];
  route_options: RouteOption[];
  pending_actions: PendingAction[];
  participant_summary: string[];
  risk_notes: string[];
  final_message: string;
  route_edit_ready?: boolean;
  base_summary?: string;
  static_risk_notes?: string[];
}

export interface ExecutionResult {
  type: string;
  status: string;
  confirmation_no?: string;
  message_id?: string;
  booking_id?: string;
}

export interface ExecutionResponse {
  execution_status: string;
  final_message: string;
  results: ExecutionResult[];
}

export interface Companion {
  name: string;
  relation: string;
  contact_value: string;
}

export interface LocationData {
  lat: number;
  lng: number;
  accuracy_m: number;
  precision: string;
  home_location: string;
  city?: string;
  district?: string;
  landmark?: string;
  formatted_address?: string;
  address_source?: string;
  address_confidence?: string;
}

export interface UserContext {
  home_location: string;
  city: string;
  coordinates?: { lat: number; lng: number };
  location_permission_granted: boolean;
  location_source: string;
  accuracy_m?: number;
  precision?: string;
  district?: string;
  landmark?: string;
  formatted_address?: string;
  address_source?: string;
  address_confidence?: string;
  manual_location_format?: string;
}
