CREATE DATABASE IF NOT EXISTS smartstack;
USE smartstack;

CREATE TABLE IF NOT EXISTS users (
  id INT NOT NULL AUTO_INCREMENT,
  username VARCHAR(50) NOT NULL,
  email VARCHAR(100) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  is_active tinyint(1) DEFAULT '0',
  PRIMARY KEY (id),
  UNIQUE KEY uq_username (username),
  UNIQUE KEY uq_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS books (
  id INT NOT NULL AUTO_INCREMENT,
  google_id VARCHAR(50) NOT NULL UNIQUE,
  title VARCHAR(255) NOT NULL,
  authors VARCHAR(255),
  categories TEXT,
  language VARCHAR(50),
  isbn VARCHAR(20),
  description TEXT,
  thumbnail VARCHAR(512),
  small_thumbnail VARCHAR(512),
  publisher VARCHAR(255),
  published_date VARCHAR(20),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_libraries (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL UNIQUE,
  PRIMARY KEY (id),
  CONSTRAINT fk_user_library_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wishlists (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL UNIQUE,
  PRIMARY KEY (id),
  CONSTRAINT fk_wishlist_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS library_books (
  library_id INT NOT NULL,
  book_id INT NOT NULL,
  added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (library_id, book_id),
  CONSTRAINT fk_library_books_library FOREIGN KEY (library_id) REFERENCES user_libraries (id) ON DELETE CASCADE,
  CONSTRAINT fk_library_books_book FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wishlist_books (
  wishlist_id INT NOT NULL,
  book_id INT NOT NULL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (wishlist_id, book_id),
  CONSTRAINT fk_wishlist_books_wishlist FOREIGN KEY (wishlist_id) REFERENCES wishlists (id) ON DELETE CASCADE,
  CONSTRAINT fk_wishlist_books_book FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
