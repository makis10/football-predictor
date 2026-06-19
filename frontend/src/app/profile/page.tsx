import { redirect } from "next/navigation";
import { getCurrentUserId, fetchWithAuth } from "@/lib/auth";
import ProfileForm from "./ProfileForm";

interface ProfileData {
  id:                number;
  email:             string;
  name:              string | null;
  image:             string | null;
  preferred_leagues: string[];
}

export default async function ProfilePage() {
  const userId = await getCurrentUserId();
  if (!userId) redirect("/login");

  const res = await fetchWithAuth("/users/me");
  if (!res.ok) redirect("/login");
  const profile: ProfileData = await res.json();

  return (
    <div className="max-w-lg mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">👤 Profile</h1>
        <p className="text-sm text-gray-500 mt-1">Manage your account settings</p>
      </div>

      <div className="rounded-2xl border border-pitch-700 bg-pitch-900 p-6">
        {/* Avatar */}
        <div className="flex items-center gap-4 mb-6">
          {profile.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={profile.image} alt="Avatar" className="w-16 h-16 rounded-full" />
          ) : (
            <div className="w-16 h-16 rounded-full bg-green-700 flex items-center justify-center text-2xl font-bold text-white">
              {profile.name?.[0]?.toUpperCase() ?? profile.email[0]?.toUpperCase() ?? "?"}
            </div>
          )}
          <div>
            <p className="font-semibold text-white">{profile.name ?? "No name set"}</p>
            <p className="text-sm text-gray-500">{profile.email}</p>
          </div>
        </div>

        <ProfileForm profile={profile} />
      </div>
    </div>
  );
}
