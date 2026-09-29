module.exports = {
  apps: [
    {
      name: 'ytdl-app',
      cwd: '/home/putra/yt-dl-python',
      script: './venv/bin/python',
      args: 'main.py',
      autorestart: true,
      max_restarts: 50,
      restart_delay: 5000,
    },
    {
      name: 'ytdl-tunnel',
      cwd: '/home/putra/yt-dl-python',
      script: './tunnel.sh',
      interpreter: 'bash',
      autorestart: true,
      max_restarts: 100,
      restart_delay: 10000,
    },
  ],
};