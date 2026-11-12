# Mock LLM for load tests (Anthropic Messages format). Config: .llmockrc.json.
FROM node:24-alpine
WORKDIR /app
RUN npm install --omit=dev llmock@3.13.0
COPY .llmockrc.json /app/.llmockrc.json
USER node
EXPOSE 8001
CMD ["npx", "llmock", "start", "--foreground"]
