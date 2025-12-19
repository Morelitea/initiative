import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Users, ListTodo, FileText, Swords, Map, Calendar, Shield, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { LogoIcon } from "@/components/LogoIcon";
import { ModeToggle } from "@/components/ModeToggle";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";

const features = [
  {
    icon: Swords,
    title: "Campaign Management",
    description:
      "Organize your TTRPG campaigns with ease. Track storylines, NPCs, and plot hooks across multiple sessions.",
  },
  {
    icon: Users,
    title: "Party Coordination",
    description:
      "Keep your gaming group in sync. Assign tasks, schedule sessions, and make sure everyone knows their role.",
  },
  {
    icon: Map,
    title: "World Building",
    description:
      "Document your lore, maps, and world details. Build rich settings your players will love to explore.",
  },
  {
    icon: ListTodo,
    title: "Quest Tracking",
    description:
      "Never lose track of side quests again. Manage objectives, rewards, and story progression in one place.",
  },
  {
    icon: FileText,
    title: "Session Notes",
    description:
      "Collaborative documents for session recaps, player handouts, and shared party knowledge.",
  },
  {
    icon: Calendar,
    title: "Event Planning",
    description:
      "Coordinate game nights, raid schedules, and guild events. Everyone stays on the same page.",
  },
];

export const LandingPage = () => {
  const { token, loading } = useAuth();
  const { resolvedTheme } = useTheme();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && token) {
      navigate("/tasks", { replace: true });
    }
  }, [token, loading, navigate]);

  if (loading) {
    return (
      <div className="bg-muted/60 flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (token) {
    return null;
  }

  const isDark = resolvedTheme === "dark";

  return (
    <div
      className="min-h-screen"
      style={{
        backgroundImage: `url(${isDark ? "/images/gridWhite.svg" : "/images/gridBlack.svg"})`,
        backgroundPosition: "center",
        backgroundBlendMode: "screen",
        backgroundSize: "72px 72px",
      }}
    >
      <div className="aurora-bg bg-muted/60">
        {/* Navigation */}
        <nav className="container mx-auto flex items-center justify-between px-4 py-4">
          <div className="text-primary flex items-center gap-2 text-xl font-semibold">
            <LogoIcon className="h-8 w-8" aria-hidden="true" />
            initiative
          </div>
          <div className="flex items-center gap-3">
            <ModeToggle />
            <Button variant="ghost" asChild>
              <Link to="/login">Sign in</Link>
            </Button>
            <Button asChild>
              <Link to="/register">Get started</Link>
            </Button>
          </div>
        </nav>

        {/* Hero Section */}
        <section className="container mx-auto px-4 py-16 text-center md:py-24">
          <div className="mx-auto max-w-3xl">
            <div className="animate-in fade-in slide-in-from-bottom-4 mb-6 flex justify-center duration-700">
              <div className="bg-primary/10 text-primary inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium">
                <Sparkles className="h-4 w-4 animate-pulse" />
                Built for gamers, by gamers
              </div>
            </div>
            <h1 className="animate-in fade-in slide-in-from-bottom-4 mb-6 text-4xl font-bold tracking-tight delay-150 duration-700 md:text-6xl">
              Roll for <span className="text-primary">Initiative</span>
            </h1>
            <p className="text-muted-foreground animate-in fade-in slide-in-from-bottom-4 mx-auto mb-8 max-w-2xl text-lg delay-300 duration-700 md:text-xl">
              A guild-based project management app built for gaming groups. Create your own guild,
              invite your party, and organize campaigns, quests, and events together—each group gets
              their own private workspace.
            </p>
            <div className="animate-in fade-in slide-in-from-bottom-4 flex flex-col items-center justify-center gap-4 delay-500 duration-700 sm:flex-row">
              <Button size="lg" className="transition-transform hover:scale-105" asChild>
                <Link to="/register">
                  <Shield className="mr-2 h-5 w-5" />
                  Start your adventure
                </Link>
              </Button>
              <Button
                size="lg"
                variant="outline"
                className="transition-transform hover:scale-105"
                asChild
              >
                <Link to="/login">Sign in to your guild</Link>
              </Button>
            </div>
          </div>
        </section>

        {/* Features Section */}
        <section className="container mx-auto px-4 py-16">
          <div className="mb-12 text-center">
            <h2 className="mb-4 text-3xl font-bold tracking-tight">Everything your party needs</h2>
            <p className="text-muted-foreground mx-auto max-w-2xl">
              Each guild gets a private workspace with projects, tasks, and documents. Whether
              you&apos;re running a D&amp;D campaign, organizing raid nights, or managing a gaming
              community—keep everything in one place.
            </p>
          </div>
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {features.map((feature, index) => (
              <Card
                key={feature.title}
                className="bg-card/50 backdrop-blur transition-all duration-300 hover:-translate-y-1 hover:shadow-lg"
                style={{ animationDelay: `${index * 100}ms` }}
              >
                <CardContent className="pt-6">
                  <div className="bg-primary/10 text-primary mb-4 inline-flex rounded-lg p-3 transition-transform duration-300 group-hover:scale-110">
                    <feature.icon className="h-6 w-6" />
                  </div>
                  <h3 className="mb-2 text-lg font-semibold">{feature.title}</h3>
                  <p className="text-muted-foreground text-sm">{feature.description}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        {/* Use Cases Section */}
        <section className="container mx-auto px-4 py-16">
          <div className="bg-card/50 mx-auto max-w-4xl rounded-2xl border p-8 text-center backdrop-blur transition-shadow duration-500 hover:shadow-xl md:p-12">
            <h2 className="mb-4 text-2xl font-bold tracking-tight md:text-3xl">
              Your guild, your way
            </h2>
            <p className="text-muted-foreground mb-6">
              Create a private guild for your group. Invite members, organize into initiatives, and
              manage projects together. Everyone stays in sync, and your data stays yours.
            </p>
            <div className="text-muted-foreground mb-8 space-y-3 text-left">
              <p className="hover:bg-primary/5 rounded-lg p-2 transition-colors">
                <strong className="text-foreground">TTRPG Groups:</strong> Manage campaigns, track
                quests, and share session notes with your adventuring party.
              </p>
              <p className="hover:bg-primary/5 rounded-lg p-2 transition-colors">
                <strong className="text-foreground">MMO Guilds:</strong> Coordinate raid schedules,
                loot distribution, and guild events.
              </p>
              <p className="hover:bg-primary/5 rounded-lg p-2 transition-colors">
                <strong className="text-foreground">Esports Teams:</strong> Track practice
                schedules, tournament prep, and team objectives.
              </p>
              <p className="hover:bg-primary/5 rounded-lg p-2 transition-colors">
                <strong className="text-foreground">Gaming Communities:</strong> Organize events,
                manage projects, and keep your community engaged.
              </p>
            </div>
            <Button size="lg" className="transition-transform hover:scale-105" asChild>
              <Link to="/register">Create your guild</Link>
            </Button>
          </div>
        </section>

        {/* CTA Section */}
        <section className="container mx-auto px-4 py-16 text-center">
          <h2 className="mb-4 text-3xl font-bold tracking-tight">Ready to level up?</h2>
          <p className="text-muted-foreground mx-auto mb-8 max-w-xl">
            Join gaming groups already using Initiative to stay organized and have more fun
            together.
          </p>
          <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Button
              size="lg"
              className="group transition-all duration-300 hover:scale-105 hover:shadow-lg"
              asChild
            >
              <Link to="/register">
                Get started for free
                <Sparkles className="ml-2 h-4 w-4 transition-transform group-hover:rotate-12" />
              </Link>
            </Button>
          </div>
        </section>

        {/* Footer */}
        <footer className="border-t">
          <div className="container mx-auto px-4 py-8">
            <div className="flex flex-col items-center justify-between gap-4 md:flex-row">
              <div className="text-primary flex items-center gap-2 font-semibold">
                <LogoIcon className="h-6 w-6" aria-hidden="true" />
                initiative
              </div>
              <p className="text-muted-foreground text-sm">
                &copy; {new Date().getFullYear()} Initiative. Roll high, stay organized.
              </p>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
};
