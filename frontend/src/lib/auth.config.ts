import type { NextAuthConfig } from 'next-auth';
import users from '@/data/users.json';

export const authConfig = {
  providers: [],
  session: { strategy: 'jwt' },
  pages: {
    signIn: '/login',
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
        const userData = users.find((u) => u.id === user.id);
        token.role = userData?.role || 'user';
        token.username = userData?.username || '';
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as any).id = token.id;
        (session.user as any).role = token.role;
        (session.user as any).username = token.username;
      }
      return session;
    },
  },
} satisfies NextAuthConfig;
