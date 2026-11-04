/*
 * AI Utilization: ~100% of this file's code
 * AI Tools Used: Claude Code (Claude Opus 5.5)
 * AI-Assisted Activities:
 *   API client development
 *   Documentation
 * Human role: plan approval, code review, and hands-on testing by Miles Cameron.
 */

import { ApiError } from './client.js';
import { followJob, pollJob } from './jobs.js';
import { pathId as id } from './request.js';

// The server keeps a batch's cards in order, and accepting or rejecting refers to their positions.
const withIndexes = (generation) => ({
  ...generation,
  cards: generation.candidates.map((card, index) => ({ ...card, index })),
});

// AI card generation: generate a batch, then accept or reject its cards. Built like
// createStudyApi, so it can be tested without fetch: request(path, { method, body }) must return
// parsed JSON and reject with an Error carrying the API's code and message. `follow` waits for a
// background job, `poll` takes over if it can't, and both can be replaced the same way.
export function createGenerateApi(request, follow = followJob, poll = pollJob) {
  const getGeneration = async (generationId) =>
    withIndexes(await request(`/api/generations/${id(generationId)}`));

  return {
    // Writing happens in a background job, so this waits for the job and then reads its batch.
    generate: async (deckId, body) => {
      const { job_id: jobId } = await request(
        `/api/decks/${id(deckId)}/generate`,
        { method: 'POST', body },
      );
      const finished = await follow(jobId).catch((error) => {
        if (error.code !== 'job_unavailable') throw error;
        return poll(jobId, request);
      });
      if (finished.status === 'failed') {
        throw new ApiError(0, 'job_failed', finished.error, finished.result?.field);
      }
      return getGeneration(finished.result.generation_id);
    },
    getGeneration,
    suggestTopics: (deckId) =>
      request(`/api/decks/${id(deckId)}/suggestions`, { method: 'POST' }),
    acceptCards: async (generationId, indexes) => {
      const accepted = await request(
        `/api/generations/${id(generationId)}/accept`,
        { method: 'POST', body: { indexes } },
      );
      return { ...accepted, generation: withIndexes(accepted.generation) };
    },
    rejectCards: async (generationId, indexes) =>
      withIndexes(await request(
        `/api/generations/${id(generationId)}/reject`,
        { method: 'POST', body: { indexes } },
      )),
  };
}
