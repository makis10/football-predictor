import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    user: {
      id?: string;
      isAdmin?: boolean;
      name?: string | null;
      email?: string | null;
      image?: string | null;
    };
  }

  interface User {
    /** DB user id resolved from the backend (OAuth path sets this in signIn). */
    dbId?: string;
    isAdmin?: boolean;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    userId?: string;
    isAdmin?: boolean;
    /** Epoch ms of the last is_admin refresh from the backend. */
    adminCheckedAt?: number;
  }
}
