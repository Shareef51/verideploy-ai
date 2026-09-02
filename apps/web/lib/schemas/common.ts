import { z } from "zod";
export const UuidSchema = z.string().uuid();
export const IsoDateSchema = z.string().datetime({ offset: true }).or(z.string().datetime());
export const ApiStatusSchema = z.string().min(1);
