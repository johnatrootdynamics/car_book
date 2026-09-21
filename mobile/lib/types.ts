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
  availability?: Record<string, { remaining: number | null; unlimited: boolean; sold_out: boolean }>;
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
