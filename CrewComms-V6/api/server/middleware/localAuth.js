const { SystemRoles } = require('librechat-data-provider');

const LOCAL_USER_ID = '6619d1a7f3a16b3a4f0d0001';

const localUser = {
  id: LOCAL_USER_ID,
  _id: LOCAL_USER_ID,
  username: 'jay-local',
  email: 'jay@local',
  name: 'Jay',
  avatar: '',
  role: SystemRoles.ADMIN,
  provider: 'local',
  plugins: [],
  createdAt: '2026-04-11T00:00:00.000Z',
  updatedAt: '2026-04-11T00:00:00.000Z',
};

const isLocalAuthEnabled = () => process.env.LIBRECHAT_LOCAL_AUTH !== '0';

const attachLocalUser = (req) => {
  req.user = { ...localUser };
};

module.exports = {
  attachLocalUser,
  isLocalAuthEnabled,
};
