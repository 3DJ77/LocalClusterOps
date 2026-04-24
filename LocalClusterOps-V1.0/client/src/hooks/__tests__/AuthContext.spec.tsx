/**
 * @jest-environment @happy-dom/jest-environment
 */
import React from 'react';
import { render, act, fireEvent } from '@testing-library/react';
import { RecoilRoot } from 'recoil';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import type { TAuthConfig } from '~/common';

import { AuthContextProvider, useAuthContext } from '../AuthContext';
import { SESSION_KEY } from '~/utils';

const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

const mockApiBaseUrl = jest.fn(() => '');

jest.mock('librechat-data-provider', () => ({
  ...jest.requireActual('librechat-data-provider'),
  setTokenHeader: jest.fn(),
  apiBaseUrl: () => mockApiBaseUrl(),
}));

let mockCapturedLoginOptions: {
  onSuccess: (...args: unknown[]) => void;
  onError: (...args: unknown[]) => void;
};

let mockCapturedLogoutOptions: {
  onSuccess: (...args: unknown[]) => void;
  onError: (...args: unknown[]) => void;
};

const mockRefreshMutate = jest.fn();

jest.mock('~/data-provider', () => ({
  useLoginUserMutation: jest.fn(
    (options: {
      onSuccess: (...args: unknown[]) => void;
      onError: (...args: unknown[]) => void;
    }) => {
      mockCapturedLoginOptions = options;
      return { mutate: jest.fn() };
    },
  ),
  useLogoutUserMutation: jest.fn(
    (options: {
      onSuccess: (...args: unknown[]) => void;
      onError: (...args: unknown[]) => void;
    }) => {
      mockCapturedLogoutOptions = options;
      return { mutate: jest.fn() };
    },
  ),
  useRefreshTokenMutation: jest.fn(() => ({ mutate: mockRefreshMutate })),
  useGetUserQuery: jest.fn(() => ({
    data: undefined,
    isError: false,
    error: null,
  })),
  useGetRole: jest.fn(() => ({ data: null })),
  useListRoles: jest.fn(() => ({ data: undefined })),
}));

const authConfig: TAuthConfig = { loginRedirect: '/login', test: true };

function TestConsumer() {
  const ctx = useAuthContext();
  return (
    <>
      <div
        data-testid="consumer"
        data-authenticated={ctx.isAuthenticated}
        data-role={ctx.user?.role ?? ''}
        data-roles={JSON.stringify(ctx.roles ?? {})}
      />
      <button data-testid="logout-default" onClick={() => ctx.logout()}>
        logout
      </button>
      <button data-testid="logout-custom" onClick={() => ctx.logout('/c/custom')}>
        logout custom
      </button>
    </>
  );
}

function renderProvider() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RecoilRoot>
        <MemoryRouter>
          <AuthContextProvider authConfig={authConfig}>
            <TestConsumer />
          </AuthContextProvider>
        </MemoryRouter>
      </RecoilRoot>
    </QueryClientProvider>,
  );
}

/** Renders without test:true; local auth still short-circuits refresh by default. */
function renderProviderLive() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RecoilRoot>
        <MemoryRouter>
          <AuthContextProvider authConfig={{ loginRedirect: '/login' }}>
            <TestConsumer />
          </AuthContextProvider>
        </MemoryRouter>
      </RecoilRoot>
    </QueryClientProvider>,
  );
}

describe('AuthContextProvider — login onError redirect handling', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.history.replaceState({}, '', '/login');
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('preserves a valid redirect_to param across login failure', () => {
    window.history.replaceState({}, '', '/login?redirect_to=%2Fc%2Fabc123');

    renderProvider();

    act(() => {
      mockCapturedLoginOptions.onError({ message: 'Invalid credentials' });
    });

    expect(mockNavigate).toHaveBeenCalledWith('/login?redirect_to=%2Fc%2Fabc123', {
      replace: true,
    });
  });

  it('drops redirect_to when it contains an absolute URL (open-redirect prevention)', () => {
    window.history.replaceState({}, '', '/login?redirect_to=https%3A%2F%2Fevil.com');

    renderProvider();

    act(() => {
      mockCapturedLoginOptions.onError({ message: 'Invalid credentials' });
    });

    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
  });

  it('drops redirect_to when it points to /login (recursive redirect prevention)', () => {
    window.history.replaceState({}, '', '/login?redirect_to=%2Flogin');

    renderProvider();

    act(() => {
      mockCapturedLoginOptions.onError({ message: 'Invalid credentials' });
    });

    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
  });

  it('navigates to plain /login when no redirect_to param exists', () => {
    renderProvider();

    act(() => {
      mockCapturedLoginOptions.onError({ message: 'Server error' });
    });

    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
  });

  it('preserves redirect_to with query params and hash', () => {
    const target = '/c/abc123?model=gpt-4#section';
    window.history.replaceState({}, '', `/login?redirect_to=${encodeURIComponent(target)}`);

    renderProvider();

    act(() => {
      mockCapturedLoginOptions.onError({ message: 'Invalid credentials' });
    });

    const navigatedUrl = mockNavigate.mock.calls[0][0] as string;
    const params = new URLSearchParams(navigatedUrl.split('?')[1]);
    expect(decodeURIComponent(params.get('redirect_to')!)).toBe(target);
  });
});

describe('AuthContextProvider — logout onSuccess/onError handling', () => {
  const mockSetTokenHeader = jest.requireMock('librechat-data-provider').setTokenHeader;

  beforeEach(() => {
    jest.clearAllMocks();
    window.history.replaceState({}, '', '/c/some-chat');
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('calls window.location.replace and setTokenHeader(undefined) when redirect is present', () => {
    const replaceSpy = jest.spyOn(window.location, 'replace').mockImplementation(() => {});

    renderProvider();

    act(() => {
      mockCapturedLogoutOptions.onSuccess({
        message: 'Logout successful',
        redirect: 'https://idp.example.com/logout?id_token_hint=abc',
      });
    });

    expect(replaceSpy).toHaveBeenCalledWith('https://idp.example.com/logout?id_token_hint=abc');
    expect(mockSetTokenHeader).toHaveBeenCalledWith(undefined);
  });

  it('does not call window.location.replace when redirect is absent', async () => {
    const replaceSpy = jest.spyOn(window.location, 'replace').mockImplementation(() => {});

    renderProvider();

    act(() => {
      mockCapturedLogoutOptions.onSuccess({ message: 'Logout successful' });
    });

    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it('does not trigger silentRefresh after OIDC redirect', () => {
    const replaceSpy = jest.spyOn(window.location, 'replace').mockImplementation(() => {});

    renderProviderLive();
    mockRefreshMutate.mockClear();

    act(() => {
      mockCapturedLogoutOptions.onSuccess({
        message: 'Logout successful',
        redirect: 'https://idp.example.com/logout?id_token_hint=abc',
      });
    });

    expect(replaceSpy).toHaveBeenCalled();
    expect(mockRefreshMutate).not.toHaveBeenCalled();
  });
});

describe('AuthContextProvider — local auth startup', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('boots into an authenticated local operator session without token refresh', () => {
    jest.useFakeTimers();
    sessionStorage.setItem(SESSION_KEY, '/c/new?endpoint=bedrock&model=claude-sonnet-4-6');

    const { getByTestId } = renderProviderLive();

    expect(mockRefreshMutate).not.toHaveBeenCalled();
    expect(getByTestId('consumer').getAttribute('data-authenticated')).toBe('true');
    expect(getByTestId('consumer').getAttribute('data-role')).toBe('ADMIN');
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(SESSION_KEY)).toBe('/c/new?endpoint=bedrock&model=claude-sonnet-4-6');
    jest.useRealTimers();
  });

  it('keeps the current URL when no stored redirect exists', () => {
    jest.useFakeTimers();
    window.history.replaceState({}, '', '/c/new');

    const { getByTestId } = renderProviderLive();

    expect(mockRefreshMutate).not.toHaveBeenCalled();
    expect(getByTestId('consumer').getAttribute('data-authenticated')).toBe('true');
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/c/new');
    jest.useRealTimers();
  });

  it('does not re-trigger remote silentRefresh work after initial local auth bootstrap', () => {
    jest.useFakeTimers();
    sessionStorage.setItem(SESSION_KEY, '/c/abc?endpoint=bedrock');

    renderProviderLive();

    act(() => {
      jest.advanceTimersByTime(100);
    });

    expect(mockRefreshMutate).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
    jest.useRealTimers();
  });

  it('ignores unsafe stored redirect values because local auth does not consume them', () => {
    jest.useFakeTimers();
    window.history.replaceState({}, '', '/c/new');
    sessionStorage.setItem(SESSION_KEY, 'https://evil.com/steal');

    renderProviderLive();

    expect(mockRefreshMutate).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalledWith('https://evil.com/steal', expect.anything());
    expect(sessionStorage.getItem(SESSION_KEY)).toBe('https://evil.com/steal');
    jest.useRealTimers();
  });
});

describe('AuthContextProvider — local auth under subdirectory deployment', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    sessionStorage.clear();
    mockApiBaseUrl.mockReturnValue('/chat');
  });

  afterEach(() => {
    mockApiBaseUrl.mockReturnValue('');
    sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('does not attempt refresh-based path normalization when local auth is enabled', () => {
    jest.useFakeTimers();
    window.history.replaceState({}, '', '/chat/c/abc123?model=gpt-4');

    renderProviderLive();

    expect(mockRefreshMutate).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalledWith(
      expect.stringContaining('/chat/c/'),
      expect.anything(),
    );
    jest.useRealTimers();
  });

  it('leaves the browser at the base path when local auth boots there', () => {
    jest.useFakeTimers();
    window.history.replaceState({}, '', '/chat');

    renderProviderLive();

    expect(mockRefreshMutate).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/chat');
    jest.useRealTimers();
  });
});

describe('AuthContextProvider — logout error handling', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.history.replaceState({}, '', '/c/some-chat');
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('keeps the local operator authenticated when logout is invoked offline', () => {
    jest.useFakeTimers();
    const { getByTestId } = renderProvider();

    fireEvent.click(getByTestId('logout-default'));
    act(() => {
      jest.advanceTimersByTime(100);
    });

    expect(getByTestId('consumer').getAttribute('data-authenticated')).toBe('true');
    expect(mockNavigate).toHaveBeenCalledWith('/c/new', { replace: true });
    jest.useRealTimers();
  });
});

describe('AuthContextProvider — custom role detection and fetching', () => {
  const mockUseGetRole = jest.requireMock('~/data-provider').useGetRole;
  const adminPermissions = {
    name: 'ADMIN',
    permissions: { PROMPTS: { USE: true, CREATE: true } },
  };

  beforeEach(() => {
    jest.clearAllMocks();
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('calls useGetRole with enabled: true for the built-in ADMIN local operator role', () => {
    jest.useFakeTimers();

    renderProviderLive();

    const adminCalls = mockUseGetRole.mock.calls.filter(([name]: [string]) => name === 'ADMIN');
    expect(adminCalls.length).toBeGreaterThan(0);
    const lastAdminCall = adminCalls[adminCalls.length - 1];
    expect(lastAdminCall[1]).toEqual(expect.objectContaining({ enabled: true }));

    jest.useRealTimers();
  });

  it('calls useGetRole with enabled: false for the custom-role sentinel in local auth', () => {
    jest.useFakeTimers();

    renderProviderLive();

    const sentinelCalls = mockUseGetRole.mock.calls.filter(([name]: [string]) => name === '_');
    expect(sentinelCalls.length).toBeGreaterThan(0);
    for (const call of sentinelCalls) {
      expect(call[1]).toEqual(expect.objectContaining({ enabled: false }));
    }

    jest.useRealTimers();
  });

  it('does not trigger refresh mutation while resolving local role state', () => {
    jest.useFakeTimers();

    renderProviderLive();

    expect(mockRefreshMutate).not.toHaveBeenCalled();

    jest.useRealTimers();
  });

  it('includes admin role data in the roles context map when loaded for local auth', () => {
    jest.useFakeTimers();
    mockUseGetRole.mockImplementation((name: string, opts?: { enabled?: boolean }) => {
      if (name === 'ADMIN' && opts?.enabled) {
        return { data: adminPermissions };
      }
      return { data: null };
    });

    const { getByTestId } = renderProviderLive();

    const rolesAttr = getByTestId('consumer').getAttribute('data-roles') ?? '{}';
    const roles = JSON.parse(rolesAttr);
    expect(roles).toHaveProperty('ADMIN');
    expect(roles.ADMIN).toEqual(adminPermissions);

    mockUseGetRole.mockReturnValue({ data: null });
    jest.useRealTimers();
  });
});
