import { ApiError } from './client.js';
import { followJob, pollJob } from './jobs.js';
import { pathId as id } from './request.js';

// The deck tutor's endpoints. Built like createGenerateApi, so it can be tested without fetch, and
// `follow` and `poll` can be replaced the same way.
export function createTutorApi(request, follow = followJob, poll = pollJob) {
  const getTutor = (deckId) => request(`/api/decks/${id(deckId)}/tutor`);

  return {
    getTutor,
    // The turn runs in a background job, so this waits for the job and then reads the chat.
    sendMessage: async (deckId, text) => {
      const { job_id: jobId } = await request(
        `/api/decks/${id(deckId)}/tutor/messages`,
        { method: 'POST', body: { text } },
      );
      const finished = await follow(jobId).catch((error) => {
        if (error.code !== 'job_unavailable') throw error;
        return poll(jobId, request); // the stream is blocked, so ask every few seconds instead
      });
      if (finished.status === 'failed') {
        throw new ApiError(0, 'job_failed', finished.error);
      }
      return getTutor(deckId);
    },
    decideProposal: (deckId, proposalId, accept) =>
      request(`/api/decks/${id(deckId)}/tutor/proposal`, {
        method: 'POST',
        body: { proposal_id: proposalId, accept },
      }),
    resetTutor: (deckId) => request(`/api/decks/${id(deckId)}/tutor`, { method: 'DELETE' }),
  };
}
