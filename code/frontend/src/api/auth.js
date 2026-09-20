/**
 * One function per auth endpoint — WS3 (Duc).
 *
 * These talk to the real backend from WS1 (PR #8). Register and login both come back
 * with the `User` object *and* set the session cookie, so neither needs a follow-up
 * call to find out who just signed in.
 */

import { get, post } from "./client";

/**
 * 201 + User, already signed in. Throws `conflict` if the email is taken, or
 * `validation_error` (with `field`) if something breaks the rules.
 *
 * `display_name` is optional: left out of the body entirely when blank, since
 * JSON.stringify drops undefined keys and the backend treats missing and blank alike.
 */
export const register = ({ email, password, displayName }) =>
  post("/auth/register", {
    email,
    password,
    display_name: displayName?.trim() ? displayName.trim() : undefined,
  });

/** 200 + User. Any bad combination is a 401 with one deliberately vague message. */
export const login = ({ email, password }) => post("/auth/login", { email, password });

/** 204, always — logging out when already signed out isn't an error. */
export const logout = () => post("/auth/logout");

/**
 * 200 + User, or a 401 with code "unauthorized" when signed out.
 *
 * This is how the app knows on page load whether someone is still signed in, which is
 * what makes a refresh keep you where you were.
 */
export const me = () => get("/auth/me");
