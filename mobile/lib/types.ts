export type Account = {
  id: number;
  type: 'user' | 'employee' | 'admin' | 'vendor';
  name: string;
  email: string;
  must_change_password: boolean;
  role?: 'track_staff' | 'office_staff';
  track_id?: number;
  track_name?: string;
  business_name?: string;
};

export type TrackEvent = {
  id: number;
  name: string;
  date: string;
  start_time?: string | null;
  end_time?: string | null;
  type: string;
  track: { id: number; name: string; location: string };
  prices: { driver: number; spectator: number; vendor: number };
  has_driver_ticket?: boolean;
  availability?: Record<string, { sold: number; remaining: number | null; unlimited: boolean; sold_out: boolean }>;
};

export type Ticket = {
  kind: string;
  code: string;
  ticket_type: string;
  event: TrackEvent;
  checked_in_at: string | null;
  qr_value: string;
  wallet: { apple?: string; google?: string };
};

export type Car = {
  id: number;
  year: number;
  make: string;
  model: string;
  color?: string | null;
  label: string;
  image_url?: string | null;
};

export type RunParticipant = {
  driver: {
    id: number;
    username: string;
    name: string;
    initials: string;
    image_url?: string | null;
  };
  car: Car;
  entered_at: string;
  exited_at?: string | null;
};

export type RunVideo = {
  id: number;
  name: string;
  status: string;
  url?: string | null;
  uploaded_at?: string | null;
};

export type DriverRun = {
  id: number;
  status: string;
  started_at: string;
  ended_at?: string | null;
  duration_seconds?: number | null;
  event?: TrackEvent | null;
  track: { id: number; name: string; location: string };
  car?: Car | null;
  entered_at?: string | null;
  exited_at?: string | null;
  participants: RunParticipant[];
  videos: RunVideo[];
  shared: boolean;
};
